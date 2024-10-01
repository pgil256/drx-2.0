# Uses the smbus2 library to send and receive data from a
# Simple Motor Controller G2.
# Works on Linux with either Python 2 or Python 3.
#
# NOTE: The SMC's input mode must be "Serial/USB".
# NOTE: You might nee to change the 'SMBus(3)' line below to specify the
#   correct I2C bus device.
# NOTE: You might need to change the 'address = 13' line below to match
#   the device number of your Simple Motor Controller.
 
from smbus2 import SMBus, i2c_msg
import time

class SmcG2I2C(object):
  def __init__(self, bus, address):
    self.bus = bus
    self.address = address
 
  # Sends the Exit Safe Start command, which is required to drive the motor.
  def exit_safe_start(self):
    write = i2c_msg.write(self.address, [0x83])
    self.bus.i2c_rdwr(write)
 
  # Sets the SMC's target speed (-3200 to 3200).
  def set_target_speed(self, speed):
    cmd = 0x85  # Motor forward
    if speed < 0:
      cmd = 0x86  # Motor reverse
      speed = -speed
    buffer = [cmd, speed & 0x1F, speed >> 5 & 0x7F]
    write = i2c_msg.write(self.address, buffer)
    self.bus.i2c_rdwr(write)
 
  # Gets the specified variable as an unsigned value.
  def get_variable(self, id):
    write = i2c_msg.write(self.address, [0xA1, id])
    read = i2c_msg.read(self.address, 2)
    time.sleep(.1)
    try:
      self.bus.i2c_rdwr(write, read)
      b = list(read)
      return b[0] + 256 * b[1]
    except Exception as e:
      print(str(e))
      self.bus.i2c_rdwr(write, read)
      b = list(read)
      return b[0] + 256 * b[1]

  # Gets the specified variable as a signed value.
  def get_variable_signed(self, id):
    value = self.get_variable(id)
    if value >= 0x8000:
      value -= 0x10000
    return value
 
  # Gets the target speed (-3200 to 3200).
  def get_target_speed(self):
    return self.get_variable_signed(20)
 
  # Gets a number where each bit represents a different error, and the
  # bit is 1 if the error is currently active.
  # See the user's guide for definitions of the different error bits.
  def get_error_status(self):
    return self.get_variable(0)

  def setToPosition(self, speed, position):
     self.set_target_speed(speed) #negative moves out
     while(True):
       val = self.get_variable_signed(12)
       print('position {} curr {}'.format(position, val))
       if(abs(val) > position):
          self.set_target_speed(0) #stop here
          break
       time.sleep(0.1)


# Open a handle to "/dev/i2c-11", representing the I2C bus.
bus = SMBus(1)
time.sleep(1)

# Select the I2C address of the Simple Motor Controller (the device number).
address = 13
 
smc = SmcG2I2C(bus, address)
 
smc.exit_safe_start()
 
error_status = smc.get_error_status()
print("Error status: 0x{:04X}".format(error_status))
 

new_speed = -2000
smc.set_target_speed(-3200)
time.sleep(8)

position = int((4/6) * 3584)

smc.setToPosition(2500, position)
'''
for i in range(3):

   new_speed = -new_speed
   print("Setting target speed to {}.\n".format(new_speed));
   smc.set_target_speed(new_speed)

   for i in range(30):
     time.sleep(.3)
     p = smc.get_variable_signed(13)
     print('changed {} '.format(p))

smc.set_target_speed(-3200)

'''
