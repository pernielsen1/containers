objective: 
create python script uploading one file to a sharepoint location using currently logged on credentials
tests: 
test file "hello.txt" to upload are in directory "upload" located in same directory as the python script.
the files are to uploaded to sharepoint directory "Documents/uploaded_files"
before uploading the file it should renamed to a "unique name" which is to be the base name of the file followed by "_" and a ISO timestamp
after uploading the ile it should be moved to directory named "done" also located in same directory as the python script
configuration parameter constraints:
The actual name of sharepoint and other credentials should be read from a json structure
location on "input", "done"  directory and input file name should be command line parameters.

The solution should include test cases starting with the "hello.txt" going all the way to upload and restoring the situation plus clearing the "done" directory

Brief part two:
create a config_this_user.json based on the config.json and the currently available information in the current windows session

onfig_this_user.json is created. Here's what
  was pre-filled and what still needs manual
  input:

  Pre-filled from this session:
  - user_email → per.nielsen1@outlook.com
  - tenant_id →
  9188040d-6c67-4c5b-b112-36a304b66dad (the fixed
  MSA/consumer tenant ID)
  - onedrive_cid → a88215cb98efcb80

  Needs manual input (2 steps):

  1. client_id — Register a free app at
  portal.azure.com → App registrations → New
  registration. Add the delegated permission
  Files.ReadWrite under Microsoft Graph, and set
  redirect URI to http://localhost. Copy the
  Application (client) ID into the config.
  2. sharepoint_url — Your personal OneDrive has a
   SharePoint-style REST URL in the format
  https://YOURHANDLE-my.sharepoint.com/personal/pe
  r_nielsen1_outlook_com. The quickest way to find
   your exact URL is to open onedrive.live.com in
  the browser — the address bar shows it when you
  navigate to your files.

  Once those two values are filled in, rename the
  file to config.json (or pass --config
  config_this_user.json on the command line) and
  the script will work.
