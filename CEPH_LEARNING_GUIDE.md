# Ceph Codebase Learning Guide

## Overview
This guide provides a structured approach to understanding the Ceph distributed storage system codebase. Ceph is a complex system with three main components: **Monitors (MON)**, **Managers (MGR)**, and **Object Storage Daemons (OSD)**.

## Prerequisites
- Strong C++ knowledge
- Understanding of distributed systems concepts
- Familiarity with storage systems
- Basic knowledge of Python (for MGR modules)

---

## Phase 1: Foundation & Architecture (Week 1-2)

### 1.1 High-Level Architecture Understanding

**Start Here:**
- [`doc/architecture.rst`](doc/architecture.rst) - Complete architecture overview
- [`README.md`](README.md) - Build instructions and getting started
- [`doc/dev/internals.rst`](doc/dev/internals.rst) - Internal architecture documentation

**Key Concepts to Understand:**
- **RADOS** (Reliable Autonomic Distributed Object Store) - The foundation
- **CRUSH Algorithm** - Data placement without central lookup
- **Cluster Map** - 5 maps that define cluster state (Monitor, OSD, PG, CRUSH, MDS)
- **Placement Groups (PGs)** - Logical grouping of objects
- **Object Storage** - How data is stored as objects with metadata

**Architecture Diagram:**
```
┌─────────────────────────────────────────────────┐
│              Ceph Clients                       │
│  (Block Device, Object Storage, File System)    │
└────────────┬────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────┐
│           RADOS Layer (librados)                │
└─────┬───────────────┬───────────────┬───────────┘
      │               │               │
      ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Monitor  │   │ Manager  │   │   OSD    │
│  (MON)   │   │  (MGR)   │   │          │
│          │   │          │   │          │
│ Cluster  │   │ Monitor  │   │  Data    │
│  State   │   │ Plugins  │   │ Storage  │
└──────────┘   └──────────┘   └──────────┘
```

### 1.2 Build and Run Development Cluster

**Setup Steps:**
```bash
# 1. Install dependencies
./install-deps.sh

# 2. Build Ceph
./do_cmake.sh
cd build
ninja -j3

# 3. Start a test cluster (3 MONs, 3 MGRs, 3 OSDs)
cd build
OSD=3 MON=3 MGR=3 ../src/vstart.sh -n -x

# 4. Check cluster health
./bin/ceph -s
./bin/ceph health detail

# 5. Stop cluster when done
../src/stop.sh
```

**Useful vstart.sh flags:**
- `-n` - Create new cluster (don't reuse existing data)
- `-x` - Enable debugging
- `-d` - Run daemons in background
- `--bluestore` - Use BlueStore backend (default)

---

## Phase 2: Component Deep Dive

### 2.1 Monitor (MON) Component (Week 3)

**Purpose:** Maintains cluster state, provides cluster maps, handles consensus via Paxos

**Key Files to Study:**
- [`src/mon/Monitor.h`](src/mon/Monitor.h) - Main monitor class
- [`src/mon/Monitor.cc`](src/mon/Monitor.cc) - Monitor implementation
- [`src/mon/Paxos.h`](src/mon/Paxos.h) - Paxos consensus algorithm
- [`src/mon/Elector.h`](src/mon/Elector.h) - Leader election
- [`src/mon/OSDMonitor.cc`](src/mon/OSDMonitor.cc) - OSD map management
- [`src/mon/MonMap.h`](src/mon/MonMap.h) - Monitor map structure

**Key Concepts:**
- **Paxos Consensus** - How monitors agree on cluster state
- **PaxosService** - Base class for monitor services (OSDMonitor, MDSMonitor, etc.)
- **Quorum** - Majority of monitors must agree
- **Cluster Maps** - Monitor maintains master copies

**Learning Path:**
1. Start with [`Monitor.h`](src/mon/Monitor.h) header comments (lines 16-22)
2. Understand the election process in [`Elector.cc`](src/mon/Elector.cc)
3. Study Paxos implementation in [`Paxos.cc`](src/mon/Paxos.cc)
4. Examine how OSD map updates work in [`OSDMonitor.cc`](src/mon/OSDMonitor.cc)

**Documentation:**
- [`doc/dev/mon-bootstrap.rst`](doc/dev/mon-bootstrap.rst) - Monitor bootstrap process
- [`doc/dev/mon-elections.rst`](doc/dev/mon-elections.rst) - Election algorithm
- [`doc/dev/mon-on-disk-formats.rst`](doc/dev/mon-on-disk-formats.rst) - Data persistence

**Hands-On Exercise:**
```bash
# Watch monitor logs in real-time
tail -f build/out/mon.*.log

# Trigger an election
./bin/ceph mon dump
./bin/ceph tell mon.a mon_status
```

### 2.2 Manager (MGR) Component (Week 4)

**Purpose:** Monitoring, orchestration, plugin modules (dashboard, prometheus, etc.)

**Key Files to Study:**
- [`src/mgr/Mgr.h`](src/mgr/Mgr.h) - Main manager class
- [`src/mgr/Mgr.cc`](src/mgr/Mgr.cc) - Manager implementation
- [`src/mgr/DaemonServer.h`](src/mgr/DaemonServer.h) - Handles daemon connections
- [`src/mgr/PyModuleRegistry.h`](src/mgr/PyModuleRegistry.h) - Python module management
- [`src/mgr/ActivePyModules.h`](src/mgr/ActivePyModules.h) - Active Python modules

**Key Concepts:**
- **Python Modules** - Extensible plugin system
- **DaemonState** - Tracks state of all daemons
- **ClusterState** - Maintains cluster-wide state
- **Metrics Collection** - Performance counters and statistics

**Python Module Locations:**
- [`src/pybind/mgr/`](src/pybind/mgr/) - Built-in manager modules
  - `dashboard/` - Web UI
  - `prometheus/` - Metrics export
  - `orchestrator/` - Cluster orchestration
  - `balancer/` - Data balancing

**Learning Path:**
1. Understand manager initialization in [`Mgr.cc`](src/mgr/Mgr.cc)
2. Study Python module loading in [`PyModuleRegistry.cc`](src/mgr/PyModuleRegistry.cc)
3. Examine daemon communication in [`DaemonServer.cc`](src/mgr/DaemonServer.cc)
4. Look at a simple module like `hello` or `selftest`

**Hands-On Exercise:**
```bash
# List active modules
./bin/ceph mgr module ls

# Enable/disable a module
./bin/ceph mgr module enable dashboard
./bin/ceph mgr module disable dashboard

# View manager status
./bin/ceph mgr stat
./bin/ceph mgr services
```

### 2.3 OSD Component (Week 5-6)

**Purpose:** Stores data, handles replication, recovery, and scrubbing

**Key Files to Study:**
- [`src/osd/OSD.h`](src/osd/OSD.h) - Main OSD class
- [`src/osd/OSD.cc`](src/osd/OSD.cc) - OSD implementation
- [`src/osd/PG.h`](src/osd/PG.h) - Placement Group
- [`src/osd/PrimaryLogPG.cc`](src/osd/PrimaryLogPG.cc) - Primary PG operations
- [`src/osd/ReplicatedBackend.cc`](src/osd/ReplicatedBackend.cc) - Replication logic
- [`src/osd/ECBackend.cc`](src/osd/ECBackend.cc) - Erasure coding backend
- [`src/osd/PeeringState.cc`](src/osd/PeeringState.cc) - PG peering state machine

**Key Concepts:**
- **Placement Groups (PGs)** - Logical grouping of objects
- **Peering** - Process of OSDs agreeing on PG state
- **Recovery** - Restoring missing/outdated objects
- **Scrubbing** - Data integrity verification
- **BlueStore** - Modern storage backend (vs FileStore)
- **ObjectStore Interface** - Abstraction for storage backends

**OSD Architecture:**
```
┌─────────────────────────────────────┐
│            OSD Daemon               │
├─────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐        │
│  │    PG    │  │    PG    │  ...   │
│  │ (Primary)│  │ (Replica)│        │
│  └────┬─────┘  └────┬─────┘        │
│       │             │               │
│  ┌────▼─────────────▼────┐         │
│  │   ObjectStore API     │         │
│  └────────┬──────────────┘         │
│           │                         │
│  ┌────────▼──────────────┐         │
│  │     BlueStore         │         │
│  │  (RocksDB + Block)    │         │
│  └───────────────────────┘         │
└─────────────────────────────────────┘
```

**Learning Path:**
1. Start with OSD initialization in [`OSD.cc`](src/osd/OSD.cc)
2. Understand PG structure in [`PG.h`](src/osd/PG.h)
3. Study peering state machine in [`PeeringState.cc`](src/osd/PeeringState.cc)
4. Examine read/write operations in [`PrimaryLogPG.cc`](src/osd/PrimaryLogPG.cc)
5. Learn about BlueStore in [`src/os/bluestore/BlueStore.h`](src/os/bluestore/BlueStore.h)

**Documentation:**
- [`doc/dev/osd_internals/`](doc/dev/osd_internals/) - OSD internals documentation
- [`doc/dev/peering.rst`](doc/dev/peering.rst) - Peering process
- [`doc/dev/placement-group.rst`](doc/dev/placement-group.rst) - PG concepts
- [`doc/dev/bluestore.rst`](doc/dev/bluestore.rst) - BlueStore architecture

**Hands-On Exercise:**
```bash
# Create a pool and write data
./bin/ceph osd pool create testpool 32
./bin/rados -p testpool put testobj /etc/hosts

# Check PG mapping
./bin/ceph osd map testpool testobj

# View OSD status
./bin/ceph osd tree
./bin/ceph osd stat

# Watch OSD logs
tail -f build/out/osd.*.log
```

---

## Phase 3: Inter-Component Communication (Week 7)

### 3.1 Messaging System

**Key Files:**
- [`src/msg/Messenger.h`](src/msg/Messenger.h) - Messaging interface
- [`src/msg/Message.h`](src/msg/Message.h) - Base message class
- [`src/msg/async/AsyncMessenger.h`](src/msg/async/AsyncMessenger.h) - Async implementation
- [`src/messages/`](src/messages/) - All message types

**Key Concepts:**
- **Messenger** - Abstraction for network communication
- **Message Types** - Strongly typed messages (MOSDOp, MOSDOpReply, etc.)
- **Dispatcher** - Message handling interface
- **Connection** - Persistent connection between daemons

**Common Message Types:**
- `MOSDOp` - Client operation to OSD
- `MOSDOpReply` - OSD response to client
- `MOSDPGInfo` - PG state information
- `MMonMap` - Monitor map distribution
- `MMgrReport` - Daemon reports to manager

**Documentation:**
- [`doc/dev/messenger.rst`](doc/dev/messenger.rst) - Messenger architecture
- [`doc/dev/network-protocol.rst`](doc/dev/network-protocol.rst) - Network protocol

### 3.2 Tracing a Read/Write Operation

**Write Operation Flow:**
```
Client
  │
  ├─> librados (RADOS client library)
  │
  ├─> MOSDOp message → Primary OSD
  │                      │
  │                      ├─> PG::do_op()
  │                      │
  │                      ├─> Write to ObjectStore
  │                      │
  │                      ├─> Replicate to replica OSDs
  │                      │
  │                      └─> MOSDOpReply → Client
  │
  └─> Operation complete
```

**Files to Trace:**
1. Client: [`src/librados/IoCtxImpl.cc`](src/librados/IoCtxImpl.cc)
2. OSD receive: [`src/osd/OSD.cc`](src/osd/OSD.cc) - `handle_op()`
3. PG processing: [`src/osd/PrimaryLogPG.cc`](src/osd/PrimaryLogPG.cc) - `do_osd_ops()`
4. Replication: [`src/osd/ReplicatedBackend.cc`](src/osd/ReplicatedBackend.cc)
5. Storage: [`src/os/bluestore/BlueStore.cc`](src/os/bluestore/BlueStore.cc)

**Hands-On Exercise:**
```bash
# Enable debug logging for specific subsystems
./bin/ceph tell osd.0 config set debug_osd 20
./bin/ceph tell osd.0 config set debug_ms 1

# Perform a write and watch logs
./bin/rados -p testpool put myobj myfile.txt
tail -f build/out/osd.0.log | grep myobj
```

---

## Phase 4: Key Data Structures & Algorithms (Week 8)

### 4.1 CRUSH Algorithm

**Files:**
- [`src/crush/CrushWrapper.h`](src/crush/CrushWrapper.h) - CRUSH map wrapper
- [`src/crush/mapper.c`](src/crush/mapper.c) - Core CRUSH algorithm
- [`src/osd/OSDMap.cc`](src/osd/OSDMap.cc) - OSD map with CRUSH

**Key Concepts:**
- **Deterministic Placement** - Same input always produces same output
- **Failure Domains** - Rack, host, OSD hierarchy
- **CRUSH Rules** - Define placement policies
- **Bucket Types** - Uniform, list, tree, straw

**Documentation:**
- [`doc/dev/crush-msr.rst`](doc/dev/crush-msr.rst) - CRUSH implementation

### 4.2 Important Data Structures

**OSDMap** ([`src/osd/osd_types.h`](src/osd/osd_types.h)):
- Cluster topology
- OSD states (up/down, in/out)
- Pool configurations
- CRUSH map

**PGMap** ([`src/mon/PGMap.h`](src/mon/PGMap.h)):
- PG states
- Statistics per PG
- Cluster-wide statistics

**ObjectStore Transaction** ([`src/os/ObjectStore.h`](src/os/ObjectStore.h)):
- Atomic operations
- Write-ahead logging
- Consistency guarantees

---

## Phase 5: Testing & Contributing (Week 9-10)

### 5.1 Testing Infrastructure

**Test Locations:**
- [`src/test/`](src/test/) - Unit tests
- [`qa/`](qa/) - Integration tests
- [`qa/suites/`](qa/suites/) - Test suites

**Running Tests:**
```bash
# Build and run all unit tests
cd build
ninja
ctest -j$(nproc)

# Run specific test
ctest -R test_name -V

# Run integration tests (requires teuthology setup)
cd qa
./run-standalone.sh tasks.ceph.test_rados
```

**Documentation:**
- [`doc/dev/testing.rst`](doc/dev/testing.rst) - Testing guide
- [`doc/dev/development-workflow.rst`](doc/dev/development-workflow.rst) - Development workflow

### 5.2 Code Navigation Tips

**Use grep/ripgrep for code search:**
```bash
# Find all uses of a function
rg "function_name" src/

# Find message type definitions
rg "class MOSDOp" src/messages/

# Find where a config option is used
rg "osd_max_write_size" src/
```

**Use ctags/cscope:**
```bash
# Generate tags
ctags -R src/

# Or use cscope
cscope -R -b
```

**IDE Setup:**
- VSCode with C++ extension
- CLion with CMake support
- Vim/Emacs with LSP (clangd)

---

## Recommended Learning Order

### Week 1-2: Foundation
- [ ] Read architecture documentation
- [ ] Build and run development cluster
- [ ] Understand RADOS and CRUSH concepts
- [ ] Explore cluster maps

### Week 3: Monitor Deep Dive
- [ ] Study Monitor class structure
- [ ] Understand Paxos consensus
- [ ] Trace monitor election
- [ ] Examine OSDMonitor operations

### Week 4: Manager Deep Dive
- [ ] Study Manager class structure
- [ ] Understand Python module system
- [ ] Examine a simple module
- [ ] Study daemon state tracking

### Week 5-6: OSD Deep Dive
- [ ] Study OSD class structure
- [ ] Understand PG concept
- [ ] Trace peering state machine
- [ ] Study read/write operations
- [ ] Examine BlueStore backend

### Week 7: Communication
- [ ] Study messaging system
- [ ] Trace a complete read operation
- [ ] Trace a complete write operation
- [ ] Understand replication flow

### Week 8: Algorithms & Data Structures
- [ ] Study CRUSH algorithm
- [ ] Understand key data structures
- [ ] Examine recovery algorithms
- [ ] Study scrubbing process

### Week 9-10: Testing & Contributing
- [ ] Run unit tests
- [ ] Write a simple test
- [ ] Fix a small bug
- [ ] Submit a patch

---

## Useful Resources

### Documentation
- Official Docs: https://docs.ceph.com/
- Developer Guide: [`doc/dev/developer_guide/`](doc/dev/developer_guide/)
- Architecture: [`doc/architecture.rst`](doc/architecture.rst)

### Community
- Mailing List: dev@ceph.io
- IRC: #ceph-devel on OFTC
- GitHub: https://github.com/ceph/ceph

### Papers & Presentations
- RADOS Paper: "RADOS: A Scalable, Reliable Storage Service for Petabyte-scale Storage Clusters"
- CRUSH Paper: "CRUSH: Controlled, Scalable, Decentralized Placement of Replicated Data"
- Ceph Paper: "Ceph: A Scalable, High-Performance Distributed File System"

### Key Configuration Files
- [`src/common/options.cc`](src/common/options.cc) - All configuration options
- [`src/sample.ceph.conf`](src/sample.ceph.conf) - Sample configuration

---

## Tips for Success

1. **Start Small**: Don't try to understand everything at once
2. **Use Logs**: Enable debug logging to see what's happening
3. **Draw Diagrams**: Visualize component interactions
4. **Run Experiments**: Modify code and observe behavior
5. **Ask Questions**: Use mailing lists and IRC
6. **Read Tests**: Tests show how components are used
7. **Follow the Data**: Trace how data flows through the system
8. **Be Patient**: Ceph is complex; understanding takes time

---

## Quick Reference Commands

```bash
# Cluster status
./bin/ceph -s
./bin/ceph health detail

# Component status
./bin/ceph mon stat
./bin/ceph mgr stat
./bin/ceph osd stat

# View maps
./bin/ceph mon dump
./bin/ceph osd dump
./bin/ceph osd tree

# Performance
./bin/ceph osd perf
./bin/ceph daemon osd.0 perf dump

# Configuration
./bin/ceph config dump
./bin/ceph config show osd.0

# Logs
tail -f build/out/*.log
```

---

## Next Steps

After completing this guide, you should:
1. Pick a specific area of interest (MON, MGR, or OSD)
2. Find an open issue on GitHub to work on
3. Join the developer mailing list
4. Attend Ceph developer meetings
5. Consider contributing documentation improvements

Good luck with your Ceph journey! 🚀