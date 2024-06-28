# mister-skinnylegs

mister-skinnylegs is an open plugin framework for parsing website/webapp 
artifacts in browser data. 
It currently provides a command line interface (CLI) for running the 
plugins against a Chrome or Chromium Profile Folder.

## The CLI Tool
### Setting up the CLI tool
The tool requires [Python](https://python.org) 3.10 or above. Once this is 
installed, download the code from this repository and put it in a folder.

The tool some dependencies which will need to be downloaded. We recommend 
using a Python venv (virtual environment) for this.

From within a shell for the folder containing the source code you would do 
the following (substitute "py" for "python" if not on Windows):

```commandline
py -m venv .venv
./.venv/Scripts/activiate
pip install -r requirements.txt
```

Line by line this:
1. Initializes a new venv
2. Activates the venv
3. Installs the dependencies listed in the requirements.txt file

The first and final step is only required once per installation. The middle
step is required each time you open a new shell to run the tool.

### PowerShell Issues?

If you are using powershell and get an error message at step two, this is 
usually due to an execution policy violation. This can usually be fixed by
executing the following ahead of the operations listed above:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Unrestricted
```

And once you're done, for safety, set the policy back to default:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Default
```

### Using the CLI
Once the tool is set up, it can be run from the command line. The tool takes
two arguments:
* The path to the profile folder
* An output folder path (the folder should not exist yet)

```commandline
py .\mister-skinnylegs.py "c:\Users\you\AppData\Local\Google\Chrome\User Data\Profile 1" output_folder
```

This will run every plugin found in the `plugins` folder against the profile
folder, generating output in the output folder.

## Contributing
### Plugins
Mister Skinnylegs plugins are represented by python modules placed in the
`plugins` folder. The filenames for plugins should end with `_plugin.py`, 
e.g., `cool_website_plugin.py`. Each plugin can contain functionality for
processing multiple *artifacts*.

Every plugin file must contain a module level variable named `__artifacts__`.
This variable should point to an iterable (tuple is suggested) of 
`ArtifactSpec` objects. E.g.,

```python
__artifacts__ = (
    ArtifactSpec(
        "Example Service",
        "Example artifact 1",
        "Description of this artifact goes here",
        "0.1.0",
        example_artifact1_func,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Example Service",
        "Example artifact 2",
        "Example which returns all hosts for local storage",
        "0.1.0",
        example_artifact2_func,
        ReportPresentation.table
    )
)
```

`ArtifactSpec` objects describe an artifact that can be processed by the 
plugin, and point to the function which provides the processing 
functionality for that artifact.

The plugin functions are required to have the following signature:

```python
def example_artifact1(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    ...
```

* The first argument will be the ChromiumProfileFolder passed to the 
  function by the host which is used to access data stored by the browser.
  More information on this class can be found in 
  [the ccl_chromium_reader package](https://github.com/cclgroupltd/ccl_chromium_reader)
* The second argument will be a logging callback function for the plugin
  to use, which should be a function that takes a sing string argument which 
  is the message to be logged
* An object which implements the ArtifactStorage abstract base class. This
  object can be used by the plugin to create writable streams which are can
  be used to store data related to the output

The function should return an `ArtifactResult` which holds the processed
data to be passed back to the host. The result held by the returned object
should be a Python data structure that can be JSON'd by the host. In the
current version, the host will use the standard `json.dump` function 
without custom encoding which means that the result should only contain
dicts, lists, strings, floats, ints, bools and None (this may change in
future versions where other common data-types, such as datetime.datetime,
will be encoded in a standard way). 

A minimal example of a plugin can be found in 
[example_plugin_.py](plugins/example_plugin_.py) 