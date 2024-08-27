```
╔╦╗┬┌─┐┌┬┐┌─┐┬─┐            
║║║│└─┐ │ ├┤ ├┬┘            
╩ ╩┴└─┘ ┴ └─┘┴└─            
╔═╗┬┌─┬┌┐┌┌┐┌┬ ┬┬  ┌─┐┌─┐┌─┐
╚═╗├┴┐│││││││└┬┘│  ├┤ │ ┬└─┐
╚═╝┴ ┴┴┘└┘┘└┘ ┴ ┴─┘└─┘└─┘└─┘
```
mister-skinnylegs is an open plugin framework for parsing website/webapp 
artifacts in browser data. 
It currently provides a command line interface (CLI) for running the 
plugins against a Chrome or Chromium Profile Folder.

## Current Plugins
| Plugin File               | Service         | Artifact                              | Version | Description                                                                                               |
|---------------------------|-----------------|---------------------------------------|---------|-----------------------------------------------------------------------------------------------------------|
| bing_plugin.py            | Bing            | Bing searches                         | 0.1     | Recovers Bing searches from URLs in history, cache                                                        |
| chatgpt_plugin.py         | ChatGPT         | ChatGPT Chat Information              | 0.1     | Recovers ChatGPT chat information from History and Cache                                                  |
| chatgpt_plugin.py         | ChatGPT         | ChatGPT User Information              | 0.1     | Recovers ChatGPT user information from Cache                                                              |
| coinbase_plugin.py        | Coinbase        | Coinbase Payment Methods              | 0.1     | Recovers Coinbase Payement Methods records from the Cache                                                 |
| coinbase_plugin.py        | Coinbase        | Coinbase User Details                 | 0.1     | Recovers Coinbase User Details records from the Cache                                                     |
| coinbase_plugin.py        | Coinbase        | Coinbase Balances                     | 0.1     | Recovers Coinbase Balances records from the Cache                                                         |
| coinbase_plugin.py        | Coinbase        | Coinbase Transactions                 | 0.1     | Recovers Coinbase Transactions from the Cache                                                             |
| discord_plugin.py         | Discord         | Discord Chat Messages                 | 0.1     | Recovers Discord chat messages from the Cache                                                             |
| dropbox_plugin.py         | Dropbox         | Dropbox Session Storage User Activity | 0.3     | Recovers user activity from 'uxa' records in Session Storage                                              |
| dropbox_plugin.py         | Dropbox         | Dropbox File System                   | 0.2     | Recovers a partial file system from URLs in the history                                                   |
| dropbox_plugin.py         | Dropbox         | Dropbox Thumbnails                    | 0.4     | Recovers thumbnails for files stored in Dropbox                                                           |
| duckduckgo_plugin.py      | Duckduckgo      | Duckduckgo searches                   | 0.1     | Recovers Duckduckgo searches from URLs in history, cache                                                  |
| google_drive_plugin.py    | Google Drive    | Google Drive Files and Folders        | 0.2     | Recovers Google Drive and Docs folder and file names (and urls) from history records                      |
| google_drive_plugin.py    | Google Drive    | Google Drive Thumbnails               | 0.2     | Recovers Google Drive thumbnails from the cache                                                           |
| google_drive_plugin.py    | Google Drive    | Google Drive Usage                    | 0.2     | Recovers indications of Google Drive usage                                                                |
| google_plugin.py          | Google          | Google searches                       | 0.4     | Recovers google searches from URLs in history, session storage, cache                                     |
| o365_sharepoint_plugin.py | O365-Sharepoint | O365-Sharepoint recent files          | 0.2     | Recovers recent files list and any thumbnails from API responses in the cache for Sharepoint and O365     |
| o365_sharepoint_plugin.py | O365-Sharepoint | O365-Sharepoint user activity         | 0.2     | Recovers artifacts related to user activity (viewing, editing, downloading, etc.) for Sharepoint and O365 |
| storage_dump_plugin.py    | Data Dump       | History                               | 0.2     | Dumps History Records                                                                                     |
| storage_dump_plugin.py    | Data Dump       | Downloads                             | 0.2     | Dumps Download Records                                                                                    |
| storage_dump_plugin.py    | Data Dump       | Localstorage                          | 0.2     | Dumps Localstorage Records                                                                                |
| storage_dump_plugin.py    | Data Dump       | Sessionstorage                        | 0.1     | Dumps Sessionstorage Records                                                                              |


## The CLI Tool
### Setting up the CLI tool
The tool requires [Python](https://python.org) 3.12 or above. Once this is 
installed, download the code from this repository and put it in a folder.

The tool some dependencies which will need to be downloaded. We recommend 
using a Python venv (virtual environment) for this.

From within a shell for the folder containing the source code you would do 
the following (substitute "py" for "python" if not on Windows):

```commandline
py -m venv .venv
./.venv/Scripts/activate
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
Once the tool is set up, it can be run from the command line. The command line 
interface begins with the browser type to be processed followed by options 
specific to that browser. The browser types currently supported by the tool 
are:

* `chromium`
* `mozilla`

To see command line help for the specific browser type, you can use the
`--help` command line option, e.g.,

```commandline
py .\mister-skinnylegs.py chromium --help
```

By default, using the tool will run every plugin found in the `plugins` 
folder against the profile folder, generating output in the output folder. 
All plugins at least generate a json file per artifact, but other outputs 
may also be created depending on the plugin. In this version, if you want
to omit a plugin from the process, you will need to remove it from the 
`plugins` folder.

#### chromium
This mode is designed to be used with data from Chrome and other browsers 
which are based on Chromium and closely follow Chrome's implementation of 
the key artefacts (e.g., Edge).

It requires two parameters:
* `-p <PROFILE_FOLDER_PATH>`
* `-o <OUTPUT_FOLDER_PATH>` 

*(NB the folder for the output path should not already exist).*

It can optionally take the following parameter:
* `-c <CACHE_FOLDER_PATH>`

The cache folder parameter is for if you need to point the tool at
a cache folder located outside the profile folder (e.g., in the case of 
Android).

Example:
```commandline
py .\mister-skinnylegs.py chromium -p "c:\Users\you\AppData\Local\Google\Chrome\User Data\Profile 1" -o .\output_folder
```

#### mozilla
This mode is designed to be used with data from the Mozilla Firefox browser
or another browser based on Firefox which closely follows the layout of
data used in Firefox.

It requires three parameters:
* `-p <PROFILE_FOLDER_PATH>`
* `-c <CACHE_FOLDER_PATH>`
* `-o <OUTPUT_FOLDER_PATH>` 

*(NB the folder for the output path should not already exist).*

Example:
```commandline
py .\mister-skinnylegs.py mozilla -p "C:\Users\you\AppData\Roaming\Mozilla\Firefox\Profiles\a4pugz09.default-release" -c "C:\Users\you\AppData\Local\Mozilla\Firefox\Profiles\a4pugz09.default-release\cache2" -o .\output_folder
```

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
def example_artifact1(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
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
current version, the host will use `json.dump` using an extended encoder
which means that the result can contain `datetime.datetime` objects along with
dicts, lists, strings, floats, ints, bools and None (this may change in
future versions where other common data-types, such as datetime.datetime,
will be encoded in a standard way). 

A minimal example of a plugin can be found in 
[example_plugin_.py](plugins/example_plugin_.py) 

#### chrome-profile-view
We have released another project which might assist in the research of new
browser artifacts which you can find here: 
https://github.com/cclgroupltd/chrome-profile-view/
