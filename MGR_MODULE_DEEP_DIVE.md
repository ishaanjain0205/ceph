# Ceph Manager Module Deep Dive

## Overview

This guide provides an in-depth look at Ceph Manager (MGR) modules, their architecture, and how they interact with the rest of the system. We'll use the **devicehealth** module as a detailed case study.

---

## Table of Contents

1. [Manager Module Architecture](#manager-module-architecture)
2. [Module Lifecycle](#module-lifecycle)
3. [Creating a Manager Module](#creating-a-manager-module)
4. [Device Health Module Case Study](#device-health-module-case-study)
5. [Module Communication Patterns](#module-communication-patterns)
6. [Best Practices](#best-practices)

---

## Manager Module Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────┐
│              Ceph Manager Daemon                    │
├─────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────┐  │
│  │      PyModuleRegistry (C++)                  │  │
│  │  - Loads Python modules                      │  │
│  │  - Manages module lifecycle                  │  │
│  │  - Provides C++ ↔ Python bridge             │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │                                    │
│  ┌──────────────▼───────────────────────────────┐  │
│  │      ActivePyModules                         │  │
│  │  - Runs enabled modules                      │  │
│  │  - Routes commands to modules                │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │                                    │
│  ┌──────────────▼───────────────────────────────┐  │
│  │   Individual Python Modules                  │  │
│  │   ┌────────────┐  ┌────────────┐            │  │
│  │   │devicehealth│  │ dashboard  │  ...       │  │
│  │   └────────────┘  └────────────┘            │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
    ┌─────────┐          ┌─────────┐
    │   MON   │          │   OSD   │
    └─────────┘          └─────────┘
```

### Key Components

#### 1. PyModuleRegistry (C++)
**Location:** [`src/mgr/PyModuleRegistry.cc`](src/mgr/PyModuleRegistry.cc)

**Responsibilities:**
- Initialize Python interpreter
- Discover and load Python modules from disk
- Maintain registry of all available modules
- Handle module enable/disable state

**Key Methods:**
```cpp
void init()                          // Initialize Python and load modules
bool handle_mgr_map(const MgrMap&)   // Update module states from cluster map
std::list<std::string> probe_modules() // Discover modules on disk
```

#### 2. MgrModule Base Class (Python)
**Location:** [`src/pybind/mgr/mgr_module.py`](src/pybind/mgr/mgr_module.py)

**Responsibilities:**
- Base class for all manager modules
- Provides API for interacting with Ceph cluster
- Handles configuration options
- Manages CLI commands
- Provides database access (SQLite)

**Key Features:**
- Configuration management
- Command execution
- Cluster state queries
- Health check reporting
- Inter-module communication

---

## Module Lifecycle

### 1. Discovery Phase

Modules are discovered by scanning the module path (default: `/usr/share/ceph/mgr`):

```python
# Module directory structure:
src/pybind/mgr/
├── devicehealth/
│   ├── __init__.py       # Makes it a Python package
│   ├── module.py         # Main module class
│   └── cli.py           # CLI command definitions
├── hello/
│   ├── __init__.py
│   ├── module.py
│   └── cli.py
└── mgr_module.py        # Base class
```

### 2. Loading Phase

**C++ Side** ([`PyModuleRegistry::init()`](src/mgr/PyModuleRegistry.cc)):
```cpp
// 1. Initialize Python interpreter
Py_Initialize();

// 2. Scan module directory
auto module_names = probe_modules(module_path);

// 3. Load each module
for (const auto& module_name : module_names) {
    auto mod = std::make_shared<PyModule>(module_name);
    int r = mod->load(pMainThreadState);
    modules[module_name] = std::move(mod);
}
```

**Python Side:**
```python
# Each module must define a Module class inheriting from MgrModule
class Module(MgrModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize module-specific state
```

### 3. Initialization Phase

When a module is enabled:

```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    
    # 1. Set default options
    for opt in self.MODULE_OPTIONS:
        setattr(self, opt['name'], opt['default'])
    
    # 2. Initialize module state
    self.run = True
    self.event = Event()

def config_notify(self):
    # 3. Load actual configuration values
    for opt in self.MODULE_OPTIONS:
        setattr(self, opt['name'], 
                self.get_module_option(opt['name']))
```

### 4. Running Phase

The `serve()` method runs in a background thread:

```python
def serve(self):
    """Main module loop - runs continuously"""
    while self.run:
        # Do background work
        self.event.wait(sleep_interval)
        self.event.clear()
```

### 5. Shutdown Phase

```python
def shutdown(self):
    """Called when module is disabled or mgr stops"""
    self.run = False
    self.event.set()  # Wake up serve() thread
```

---

## Creating a Manager Module

### Minimal Module Structure

Let's examine the **hello** module as a template:

**File: `src/pybind/mgr/hello/module.py`**

```python
from mgr_module import MgrModule, Option
from threading import Event

class Hello(MgrModule):
    # 1. Define module options
    MODULE_OPTIONS = [
        Option(
            name='place',
            default='world',
            desc='a place in the world',
            runtime=True  # Can be changed without restart
        ),
    ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run = True
        self.event = Event()
        self.config_notify()
    
    def config_notify(self):
        """Called when configuration changes"""
        for opt in self.MODULE_OPTIONS:
            setattr(self, opt['name'], 
                    self.get_module_option(opt['name']))
    
    def serve(self):
        """Background thread"""
        while self.run:
            # Do work here
            self.event.wait(60)
            self.event.clear()
    
    def shutdown(self):
        """Cleanup"""
        self.run = False
        self.event.set()
```

### Adding CLI Commands

**File: `src/pybind/mgr/hello/cli.py`**

```python
from mgr_module import CLICommandBase

# Create a command registry for this module
HelloCLICommand = CLICommandBase.make_registry_subtype("HelloCLICommand")
```

**In module.py:**

```python
from .cli import HelloCLICommand

class Hello(MgrModule):
    CLICommand = HelloCLICommand  # Register command class
    
    @HelloCLICommand.Read('hello')
    def hello(self, person_name: Optional[str] = None):
        """Say hello"""
        who = person_name or self.get_module_option('place')
        return HandleCommandResult(stdout=f'Hello, {who}!')
```

**Command Decorators:**
- `@CLICommand.Read()` - Read-only command
- `@CLICommand()` - Write command (can modify state)
- `@CLIRequiresDB` - Requires database access

---

## Device Health Module Case Study

### Purpose

The **devicehealth** module monitors storage device health metrics (SMART data) and predicts device failures to enable proactive maintenance.

### Architecture

```
┌─────────────────────────────────────────────────────┐
│         Device Health Module                        │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────────────────────────────────────┐    │
│  │  Scraping Engine                           │    │
│  │  - Queries OSDs/MONs for SMART data       │    │
│  │  - Runs periodically (default: 24h)       │    │
│  └────────────┬───────────────────────────────┘    │
│               │                                      │
│  ┌────────────▼───────────────────────────────┐    │
│  │  SQLite Database                           │    │
│  │  - Stores historical metrics               │    │
│  │  - Device table + Metrics table            │    │
│  └────────────┬───────────────────────────────┘    │
│               │                                      │
│  ┌────────────▼───────────────────────────────┐    │
│  │  Health Checker                            │    │
│  │  - Analyzes device life expectancy         │    │
│  │  - Generates health warnings               │    │
│  │  - Auto-marks out failing OSDs             │    │
│  └────────────────────────────────────────────┘    │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Key Files

1. **[`module.py`](src/pybind/mgr/devicehealth/module.py)** - Main module logic (799 lines)
2. **[`cli.py`](src/pybind/mgr/devicehealth/cli.py)** - CLI command registry (3 lines)
3. **`__init__.py`** - Package marker

### Module Options

```python
MODULE_OPTIONS = [
    Option(
        name='enable_monitoring',
        default=True,
        type='bool',
        desc='monitor device health metrics',
        runtime=True,
    ),
    Option(
        name='scrape_frequency',
        default=86400,  # 24 hours
        type='secs',
        desc='how frequently to scrape device health metrics',
        runtime=True,
    ),
    Option(
        name='retention_period',
        default=(86400 * 180),  # 180 days
        type='secs',
        desc='how long to retain device health metrics',
        runtime=True,
    ),
    Option(
        name='warn_threshold',
        default=(86400 * 14 * 6),  # 12 weeks
        type='secs',
        desc='raise health warning if OSD may fail before this long',
        runtime=True,
    ),
    Option(
        name='self_heal',
        default=True,
        type='bool',
        desc='preemptively heal cluster around devices that may fail',
        runtime=True,
    ),
]
```

### Database Schema

The module uses SQLite for persistent storage:

```python
SCHEMA = [
    """
    CREATE TABLE Device (
        devid TEXT PRIMARY KEY
    ) WITHOUT ROWID;
    """,
    """
    CREATE TABLE DeviceHealthMetrics (
        time DATETIME DEFAULT (strftime('%s', 'now')),
        devid TEXT NOT NULL REFERENCES Device (devid),
        raw_smart TEXT NOT NULL,
        PRIMARY KEY (time, devid)
    );
    """
]
```

**Key Points:**
- `Device` table: Tracks known devices
- `DeviceHealthMetrics` table: Stores SMART data over time
- Uses foreign key relationship
- Time stored as Unix epoch for easy querying

### Core Functionality

#### 1. Scraping Device Metrics

**Flow:**
```
Module.serve() 
  → scrape_all()
    → do_scrape_daemon(daemon_type, daemon_id)
      → send_command('smart') to daemon
        → extract_smart_features(raw_data)
          → put_device_metrics(devid, data)
            → Store in SQLite
```

**Code:**
```python
def scrape_all(self):
    """Scrape all OSDs and MONs"""
    osdmap = self.get("osd_map")
    for osd in osdmap['osds']:
        raw_smart_data = self.do_scrape_daemon('osd', str(osd['osd']))
        for device, raw_data in raw_smart_data.items():
            data = self.extract_smart_features(raw_data)
            if device and data:
                self.put_device_metrics(device, data)
```

**Communication with Daemons:**
```python
def do_scrape_daemon(self, daemon_type, daemon_id, devid=''):
    """Send 'smart' command to daemon"""
    result = CommandResult('')
    self.send_command(result, daemon_type, daemon_id, json.dumps({
        'prefix': 'smart',
        'format': 'json',
        'devid': devid,
    }), '')
    r, outb, outs = result.wait()
    return json.loads(outb)
```

#### 2. Health Checking

**Flow:**
```
check_health()
  → Get all devices with life_expectancy
    → For each device:
      → Check if failure imminent (< warn_threshold)
        → Generate health warning
      → Check if should mark out (< mark_out_threshold)
        → Add to mark_out list
    → Mark out OSDs if self_heal enabled
    → Set health checks
```

**Code:**
```python
def check_health(self):
    """Check device life expectancy and take action"""
    warn_threshold_td = timedelta(seconds=self.warn_threshold)
    mark_out_threshold_td = timedelta(seconds=self.mark_out_threshold)
    
    devs = self.get("devices")
    osds_to_mark_out = []
    warnings = []
    
    for dev in devs['devices']:
        if 'life_expectancy_max' not in dev:
            continue
            
        life_expectancy = datetime.strptime(
            dev['life_expectancy_max'],
            '%Y-%m-%dT%H:%M:%S.%f%z')
        
        now = datetime.now(timezone.utc)
        
        # Should we mark out?
        if life_expectancy - now <= mark_out_threshold_td:
            if self.self_heal:
                osds = [x for x in dev['daemons'] 
                        if x.startswith('osd.')]
                osds_to_mark_out.extend(osds)
        
        # Should we warn?
        if life_expectancy - now <= warn_threshold_td:
            warnings.append(
                f"{dev['devid']} may fail soon; "
                f"daemons {dev['daemons']}")
    
    # Take action
    if osds_to_mark_out:
        self.mark_out_etc(osds_to_mark_out)
    
    # Report health
    if warnings:
        self.set_health_checks({
            'DEVICE_HEALTH': {
                'severity': 'warning',
                'summary': f'{len(warnings)} device(s) may fail soon',
                'detail': warnings,
            }
        })
```

#### 3. Automatic Remediation

When a device is predicted to fail soon:

```python
def mark_out_etc(self, osd_ids):
    """Mark OSDs out and set primary-affinity to 0"""
    # 1. Mark OSD out (stop assigning new data)
    result = CommandResult('')
    self.send_command(result, 'mon', '', json.dumps({
        'prefix': 'osd out',
        'ids': osd_ids,
    }), '')
    
    # 2. Set primary-affinity to 0 (stop serving reads)
    for osd_id in osd_ids:
        result = CommandResult('')
        self.send_command(result, 'mon', '', json.dumps({
            'prefix': 'osd primary-affinity',
            'id': int(osd_id),
            'weight': 0.0,
        }), '')
```

### CLI Commands

The module provides several CLI commands:

```python
@DevicehealthCLICommand.Read('device query-daemon-health-metrics')
def do_query_daemon_health_metrics(self, who: str):
    """Get device health metrics for a given daemon"""
    # Returns current SMART data from daemon

@DevicehealthCLICommand.Read('device scrape-health-metrics')
def do_scrape_health_metrics(self, devid: Optional[str] = None):
    """Scrape and store device health metrics"""
    # Triggers immediate scrape

@DevicehealthCLICommand.Read('device get-health-metrics')
def do_get_health_metrics(self, devid: str, sample: Optional[str] = None):
    """Show stored device metrics for the device"""
    # Query historical data from database

@DevicehealthCLICommand('device check-health')
def do_check_health(self):
    """Check life expectancy of devices"""
    # Triggers health check

@DevicehealthCLICommand('device monitoring on')
def do_monitoring_on(self):
    """Enable device health monitoring"""
    self.set_module_option('enable_monitoring', True)
```

### Integration with Disk Prediction

The module can integrate with ML-based prediction modules:

```python
def predict_life_expectancy(self, devid: str):
    """Use ML model to predict device failure"""
    model = self.get_ceph_option('device_failure_prediction_mode')
    
    if model.lower() == 'local':
        plugin_name = 'diskprediction_local'
        # Call another module's method
        return self.remote(plugin_name, 'predict_life_expectancy', 
                          devid=devid)
```

---

## Module Communication Patterns

### 1. Module → Cluster

**Query Cluster State:**
```python
# Get OSD map
osdmap = self.get("osd_map")

# Get device information
devices = self.get("devices")

# Get specific device
device = self.get(f"device {devid}")

# Get configuration
config = self.get('config')
```

**Send Commands:**
```python
# To specific daemon
result = CommandResult('')
self.send_command(result, 'osd', '0', json.dumps({
    'prefix': 'command_name',
    'arg': 'value'
}), '')
r, outb, outs = result.wait()

# To monitor (cluster-wide)
result = CommandResult('')
self.send_command(result, 'mon', '', json.dumps({
    'prefix': 'osd out',
    'ids': ['0', '1']
}), '')
```

**Report Health:**
```python
self.set_health_checks({
    'CHECK_NAME': {
        'severity': 'warning',  # or 'error'
        'summary': 'Brief description',
        'detail': ['Detailed message 1', 'Detailed message 2'],
    }
})
```

### 2. Module → Module

**Call Another Module:**
```python
# Check if module is available
can_run, _ = self.remote('other_module', 'can_run')

if can_run:
    # Call method on other module
    result = self.remote('other_module', 'method_name', 
                        arg1=value1, arg2=value2)
```

### 3. Module → Database

**Using SQLite:**
```python
# Execute query
with self._db_lock, self.db:
    self.db.execute('BEGIN;')
    cursor = self.db.execute(
        "SELECT * FROM table WHERE id = ?", 
        (value,))
    for row in cursor:
        # Process row
        pass
```

### 4. Module → External Services

**HTTP Requests:**
```python
import requests

response = requests.get('https://api.example.com/data')
data = response.json()
```

---

## Best Practices

### 1. Module Structure

```
mymodule/
├── __init__.py          # Empty or imports
├── module.py            # Main Module class
├── cli.py              # CLI command registry
├── utils.py            # Helper functions (optional)
└── tests/              # Unit tests (optional)
    └── test_module.py
```

### 2. Configuration Management

```python
MODULE_OPTIONS = [
    Option(
        name='option_name',
        default=default_value,
        type='str',  # 'str', 'int', 'float', 'bool', 'secs'
        desc='Human-readable description',
        runtime=True,  # Can change without restart
        min=0,  # Optional: minimum value
        max=100,  # Optional: maximum value
    ),
]

def config_notify(self):
    """Always implement this to handle config changes"""
    for opt in self.MODULE_OPTIONS:
        setattr(self, opt['name'], 
                self.get_module_option(opt['name']))
```

### 3. Background Work

```python
def serve(self):
    """Keep this simple and responsive"""
    while self.run:
        try:
            # Do work
            self.do_work()
        except Exception as e:
            self.log.error(f"Error in serve: {e}")
        
        # Sleep with interruptible wait
        self.event.wait(self.sleep_interval)
        self.event.clear()

def shutdown(self):
    """Always implement clean shutdown"""
    self.run = False
    self.event.set()
```

### 4. Error Handling

```python
def some_operation(self):
    try:
        result = self.risky_operation()
        return 0, json.dumps(result), ''
    except KeyError as e:
        return -errno.ENOENT, '', f'Key not found: {e}'
    except ValueError as e:
        return -errno.EINVAL, '', f'Invalid value: {e}'
    except Exception as e:
        self.log.exception("Unexpected error")
        return -errno.EIO, '', str(e)
```

### 5. Logging

```python
# Use appropriate log levels
self.log.debug('Detailed debugging info')
self.log.info('Important events')
self.log.warning('Potential issues')
self.log.error('Errors that need attention')
self.log.exception('Errors with stack trace')
```

### 6. Database Usage

```python
# Always use transactions
with self._db_lock, self.db:
    self.db.execute('BEGIN;')
    try:
        # Multiple operations
        self.db.execute(sql1, params1)
        self.db.execute(sql2, params2)
        # Commit happens automatically on context exit
    except Exception:
        # Rollback happens automatically on exception
        raise

# Use parameterized queries (prevent SQL injection)
cursor = self.db.execute(
    "SELECT * FROM table WHERE id = ?",
    (user_input,)  # Never use string formatting!
)
```

### 7. Testing

```python
def self_test(self):
    """Implement self-test for validation"""
    assert self.db_ready()
    
    # Test basic operations
    result = self.some_operation()
    assert result[0] == 0, "Operation failed"
    
    self.log.info("Self-test passed")
```

---

## Adding a New Module

### Step-by-Step Guide

1. **Create module directory:**
   ```bash
   mkdir src/pybind/mgr/mymodule
   ```

2. **Create `__init__.py`:**
   ```python
   # Empty file or:
   from .module import Module
   ```

3. **Create `cli.py`:**
   ```python
   from mgr_module import CLICommandBase
   MymoduleCLICommand = CLICommandBase.make_registry_subtype("MymoduleCLICommand")
   ```

4. **Create `module.py`:**
   ```python
   from mgr_module import MgrModule, Option
   from .cli import MymoduleCLICommand
   
   class Module(MgrModule):
       CLICommand = MymoduleCLICommand
       
       MODULE_OPTIONS = [
           # Define options
       ]
       
       def __init__(self, *args, **kwargs):
           super().__init__(*args, **kwargs)
           # Initialize
       
       def serve(self):
           # Background work
           pass
       
       def shutdown(self):
           # Cleanup
           pass
   ```

5. **Build and test:**
   ```bash
   cd build
   ninja
   ../src/vstart.sh -n -x
   
   # Enable module
   ./bin/ceph mgr module enable mymodule
   
   # Check status
   ./bin/ceph mgr module ls
   ```

---

## Debugging Tips

### 1. Enable Debug Logging

```bash
# In vstart cluster
./bin/ceph config set mgr mgr/mymodule/log_level debug

# Or in module code
self.log.setLevel(logging.DEBUG)
```

### 2. Check Module Status

```bash
# List all modules
./bin/ceph mgr module ls

# Check if module is loaded
./bin/ceph mgr module ls | grep mymodule

# View module options
./bin/ceph config dump | grep mgr/mymodule
```

### 3. View Logs

```bash
# Manager logs
tail -f build/out/mgr.*.log | grep mymodule

# Filter for errors
tail -f build/out/mgr.*.log | grep -i error
```

### 4. Interactive Testing

```python
# Add to module for testing
def debug_info(self):
    """Return debug information"""
    return {
        'enabled': self.get_module_option('enable_monitoring'),
        'last_run': self.last_run_time,
        'db_ready': self.db_ready(),
    }
```

---

## Summary

Manager modules provide a powerful, extensible way to add functionality to Ceph:

- **Python-based**: Easy to develop and maintain
- **Integrated**: Full access to cluster state and operations
- **Persistent**: SQLite database for storing data
- **Reactive**: Respond to cluster events
- **Proactive**: Run background tasks
- **Safe**: Isolated from core daemons

The **devicehealth** module demonstrates advanced patterns:
- Periodic data collection
- Database storage and querying
- Health monitoring and alerting
- Automatic remediation
- Integration with other modules

Use this guide as a reference when exploring or creating manager modules!