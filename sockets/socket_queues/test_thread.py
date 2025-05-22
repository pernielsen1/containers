import socket
import threading
import time
import sys

class ThreadMonitor:
    def __init__(self):
        self.threads = []
        self.exceptions = {}
        self._lock = threading.Lock()
        self.running = True

    def add_thread(self, thread):
        with self._lock:
            self.threads.append(thread)

    def record_exception(self, thread_name, exception):
        with self._lock:
            self.exceptions[thread_name] = exception
            self.running = False  # Signal to stop all threads

    def check_threads(self):
        while self.running and all(t.is_alive() for t in self.threads):
            time.sleep(0.1)  # Check periodically

        if not self.running:
            print("Exception detected in one of the threads. Terminating all threads.")
            for thread in self.threads:
                if thread.is_alive():
                    print(f"Terminating thread: {thread.name}")
                    # It's generally not recommended to forcefully terminate threads
                    # as it can lead to resource leaks or inconsistent state.
                    # A better approach would be to signal the threads to exit gracefully.
                    # However, for the strict requirement of immediate termination, we'll proceed.
                    # Note: Python's threading module doesn't provide a direct way to forcefully stop a thread.
                    # The following is a common (though potentially unsafe) workaround using a flag.
                    if hasattr(thread, "_stop_event"):
                        thread._stop_event.set() # Assuming threads are designed to check this flag
                    # For threads that don't check a flag, a more drastic (and riskier) approach
                    # might involve os.kill on the thread's PID (if you can obtain it), but this is highly discouraged.
                    # For this example, we'll rely on the threads being designed to exit upon a signal.

        if self.exceptions:
            print("Exceptions encountered:")
            for name, exc in self.exceptions.items():
                print(f"Thread '{name}': {exc}")
            return True  # Indicate an exception occurred
        return False

def sender_thread(monitor, host, port):
    thread_name = threading.current_thread().name
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            print(f"{thread_name}: Connected to {host}:{port}")
            while True:
                message = f"Hello from sender at {time.time()}"
                s.sendall(message.encode('utf-8'))
                print(f"{thread_name}: Sent '{message}'")
                time.sleep(1)
    except Exception as e:
        monitor.record_exception(thread_name, e)
    finally:
        print(f"{thread_name}: Exiting")

def receiver_thread(monitor, host, port):
    thread_name = threading.current_thread().name
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            s.listen()
            conn, addr = s.accept()
            with conn:
                print(f"{thread_name}: Connected by {addr}")
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    print(f"{thread_name}: Received '{data.decode('utf-8')}' from {addr}")
                    time.sleep(0.5)
    except Exception as e:
        monitor.record_exception(thread_name, e)
    finally:
        print(f"{thread_name}: Exiting")

def listener_thread(monitor, host, listen_port):
    thread_name = threading.current_thread().name
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, listen_port))
            s.listen()
            print(f"{thread_name}: Listening for new connections on {listen_port}")
            while True:
                conn, addr = s.accept()
                print(f"{thread_name}: New connection from {addr}")
                # You might want to spawn a new thread to handle this connection
                conn.close() # For this example, we just accept and close
    except Exception as e:
        monitor.record_exception(thread_name, e)
    finally:
        print(f"{thread_name}: Exiting")

def monitor_thread_func(monitor):
    thread_name = threading.current_thread().name
    print(f"{thread_name}: Starting to monitor threads.")
    exception_occurred = monitor.check_threads()
    if exception_occurred:
        # Perform any necessary cleanup before exiting
        print(f"{thread_name}: Exiting due to an exception in another thread.")
        sys.exit(1)
    else:
        print(f"{thread_name}: All threads finished normally.")
        sys.exit(0)

if __name__ == "__main__":
    HOST = '127.0.0.1'
    PORT = 12345
    LISTEN_PORT = 12346

    monitor = ThreadMonitor()

    sender = threading.Thread(target=sender_thread, args=(monitor, HOST, PORT), name="SenderThread")
    receiver = threading.Thread(target=receiver_thread, args=(monitor, HOST, PORT), name="ReceiverThread")
    listener = threading.Thread(target=listener_thread, args=(monitor, HOST, LISTEN_PORT), name="ListenerThread")
    monitor_thread = threading.Thread(target=monitor_thread_func, args=(monitor,), name="MonitorThread")

    monitor.add_thread(sender)
    monitor.add_thread(receiver)
    monitor.add_thread(listener)

    sender.start()
    receiver.start()
    listener.start()
    monitor_thread.start()

    # Wait for the monitor thread to finish (either due to an exception or normal completion)
    monitor_thread.join()

    # The program will exit in the monitor thread based on the outcome.