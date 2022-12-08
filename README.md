# Python-sim900

_Library for working with the sim900 module_

Python-sim900 is a simple library for processing incoming calls and SMS messages. By default, the library does nothing with the received data. To add the necessary functionality for subsequent data processing, two functions are provided, ``additional_function_message`` for incoming messages and ``additional_function_call`` for calls. When a call is received, the call is rejected and the data about it is transmitted further.

Requirements
------------

- Python 3.10 or later
- pyserial
- python-gsmmodem

Installing and running the library
------------

Download and extract the ``python-sim900`` archive or clone from GitHub. If necessary, edit the ``additional_function_message`` and ``additional_function_call`` functions. Next, install the library:
```sh
python setup.py install
```
A simple start of the module can be carried out using the following command, in which we pass the serial port device and speed as arguments (optional parameters, by default tty "/dev/ttyUSB0"  and speed 19200)
> Note: Before running the script, you need to enable the sim900 module. Modules designed to work with arduino are usually equipped with a "Power" button.

> Note: To work with a parallel port ('/dev/ttyUSB0'), the user must have the appropriate rights

```sh
python -m sim900 /dev/ttyS0 19200
```
or by default:
```sh
python -m sim900
```
In the following example of using the library, we redefine the methods in the new class. To do this, create a python file new_sim900.py with the following action:

```python
from sim900 import *

class NewSim900(Sim900):

    def additional_function_call(self, call: Call) -> None:
        print(f"Incoming call: {call.phone}")

    def additional_function_message(self, msg: Message) -> None:
        print("Incoming message: \n" +
        '\n'.join((f"{f[0]}:\t {f[1]}" for f in msg)))



sim = NewSim900(tty='/dev/ttyUSB0')
sim.connect()
sim.pre_up()
sim.run()
```
and run the file with the following command:
```sh
python new_sim900.py
```
