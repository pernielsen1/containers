import os
import logging
from communication_app import CommunicationApplication, Filter, Message

class Dimport:
    def __init__(self, module_name, class_name):
        #__import__ method used
        # to fetch module
        module = __import__(module_name)

        # getting attribute by
        # getattr() method
        self.my_class = getattr(module, class_name)



# Main function
if __name__ == "__main__":
    # Driver Code
    print("current dir" + os.getcwd())

    logging.getLogger().setLevel(logging.DEBUG)
    myapp = CommunicationApplication('middle.json')
    obj = Dimport("simple_filters", "FilterUpper")
    upper_filter = obj.my_class(myapp, 'upper')


    msg = Message('Hello from dynamic World!' + upper_filter.app.name)
    msg_upper = upper_filter.run(msg)
    print(msg_upper.get_string())
