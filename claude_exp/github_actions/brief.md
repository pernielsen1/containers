Objective: exploring github actions for test running purposes
task: create github action on my profile where all files upload to a directory named "todo" will be handled by the python script "handle_todo.py"
definitions:
unique_file_name: a file processed consists of #basename and #extension. the unique_file_name is #basename_#isodate_and_time.#extension
the #iso_date_and_time is CCYYMMDD.HH-MM-SS formatted.
handle_todo.py: reads an ascii text file and converts all letters to uppercase
when file is processed a copy to a unique_file_name is sent to directory "next_step"
github action:
the github action should be trigger based i.e. nothing happens if no one uploads a file to the "to do" directory.
the currently logged on user has a github account. 

end_result:
Create script to create github action which is runnable with manual input of password for current github user
