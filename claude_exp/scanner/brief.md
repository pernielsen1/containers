objective: build a scanner deamon processing configurable task on files in multiple directories.

definitions:
config.json should hold a list directories to monitor for files
for each directory there is an action.
the action:
contains the name of a python script to execute
the scripts will take the name of the file as first mandatory parameter.

deamon:
deamon should scan for files every configurable no of seconds.
Note: When deamon sees a new file - it may be a large file not finalized yet. - ensure a lock on the file can be obtained.
the application has a mirror directory structure for 
"pending"
"log"
"failed"
the directories scanned will be made to exist in each of the structures above.
no inbound directory can have a lenght of above 128 chars - ensuring room for the overhead added above


processing of a file has the following steps
1: discovery - there is a file to process
2: obtain lock
3: assign a unique name adding timestamp and sequence number.
4: move file to "pending directory"
4: invoke action
5: move file to "log directory" if script returns success exit code 0 if not exit code move to "failed directory"

testing:
implement a simple action "upper" test where the file in the directory will be translated to upper case.
the inbound directory for this action is "to_upper" and I have placed a hello.txt in that



admin scripts:
the solution contains a script - install_scanner which can install the scanner in both
a windows and linux (including wsl)
the solution contains a script - stop_scanner which stops the deamon process.

further instructions 1:
make a "start_scanner.sh" script for starting scanner as deamon without installing it
when scanner started no matter if a automated startup or manual it should in ps (linux) have name pn_scanner

further instructions 2:
each action most likely need a json configuration file with input.
make directory actions where each action will have a directory.
if upon start up of the deamong an acton is found not to have the directory is created with a default json file.
the minimum default just has the entry name:

further instruction 3:
make it possible for the deamon to reload the configurations i.e. a script "reload.sh" forcing the deamon to reload configurations.

further instruction 4: 
make a test.sh which creates a file in to_upper with the "Hello Claude" as the text in the file. the file name should always be "hello.txt" if the file already exists exit script with failure

make a test.sh which creates a file in to_upper with the "Hello Claude" as the text in the file. the
  file name should always be "hello.txt" if the file already exists exit script with failure             
  good work so far - do you have any suggestions to improve the resilience of the solution 
─────────────────────────────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ accept edits on (shift+tab to cycle)     

  asked good work - any suggestions on improving the resilience of the solutio nad got this:

  ❯ good work so far - do you have any suggestions to improve the resilience of the solution               
                                                                                           
● Here are the most impactful resilience gaps I see:                                                     
                                                                                                       
  1. Orphaned pending files on crash/restart                                                             
  If the daemon dies while a file is in pending/, it stays there forever — the restart starts with an    
  empty seen set and only scans inbound dirs. On startup it should recover files stuck in pending/ back  
  to inbound, or reprocess them directly.                                                                
                                                                                                         
  2. No graceful shutdown on SIGTERM                                                                     
  stop_scanner.sh sends SIGKILL (via kill), which can interrupt mid-processing. A SIGTERM handler should 
  let the current file finish before exiting.

  3. Duplicate log entries
  Visible in scanner.log — each line appears twice because nohup redirects stdout to the log file and the
   StreamHandler also writes to stdout. The file handler and stdout handler collide when daemonized.

  4. Large file stability check
  The lock check helps but isn't foolproof on all systems. A second check — confirming file size hasn't
  changed between two polls — is more reliable for detecting still-writing files.

211
  6. Reload latency
  SIGHUP sets the flag but the daemon only checks it after time.sleep(interval) completes — up to
  scan_interval_seconds delay. The sleep could be made interruptible.

  ---
  Want me to implement all of these, or prioritise a subset?
