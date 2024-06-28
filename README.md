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
