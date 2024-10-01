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

from PyQt5 import QtCore
from PyQt5.QtCore import QTime, QTimer, QObject, QThread, pyqtSignal, pyqtSlot

class SMCG2(QtCore.QThread):
  finished = pyqtSignal()
  progress = pyqtSignal(int)
  pressureEmit = pyqtSignal(float)

  def __init__(self, bus, address, parent=None):
#    super(SMCG2, self).__init__()
    QtCore.QThread.__init__(self, parent)

    print('init smcg2')

    self.busI2C = bus
    self.address = address

    self.stack = 0

# Open a handle to "/dev/i2c-3", representing the I2C bus.
    print("Opening bus")
    self.bus = SMBus(self.busI2C)
    print("Opened bus")
 
    try:
      self.exit_safe_start()
      time.sleep(2)
      error_status = self.get_error_status()
      print("Error status: 0x{:04X}".format(error_status))
    except Exception as e:
      print('Failed to find SMC G2 ', str(e))
      return
 
    self.isRunning = True
    self.atPressure = False
    self.atDistance = False
    self.atTime = False
    
  @pyqtSlot()
  def run(self):

    print('start SMC')

    self.pressure = 0
    self.distance = 0
    self.forTime = 0
    self.reset = False

    while (self.isRunning):
      if(self.pressure > 0):
         self.moveToPressure(self.pressure)
         self.pressure = 0

      if(self.distance > 0):
         self.moveToDistance(self.distance)
         self.distance = 0

      if(self.forTime > 0):
         self.moveForTime(self.forTime)
         self.forTime = 0

      if(self.reset):
         self.moveToReset()
         self.reset = 0


      time.sleep(1)

  def setReset(self):
    self.reset = True

  def setDistance(self, distance):
    self.distance = distance
    self.atDistance = False


  def moveToDistance(self, distance):

    if(distance == 0):
      distance = 40 #offset for 0
    print('set distance {}'.format(distance))

    self.actuatorSpeedDefault = int(3200 / 2)
    while(True):
      try:
        position = self.get_variable(12)
#        print('position:', position)
        if(abs(distance - position) < 20):
           break
        if(position < distance):
          self.actuatorSpeed = self.actuatorSpeedDefault
        else:
          self.actuatorSpeed = -self.actuatorSpeedDefault
        self.setTargetSpeed(self.actuatorSpeed)
        self.exit_safe_start()
      except Exception as e:
        print(str(e))
        self.setTargetSpeed(0)

      time.sleep(0.1)

    self.setTargetSpeed(0)

  def moveForTime(self, forTime):

    print('set time {}'.format(forTime))
    self.actuatorSpeedDefault = int(3200 / 4)
    if(forTime > 0):
      self.actuatorSpeed = self.actuatorSpeedDefault
    else:
      forTime = - forTime
      self.actuatorSpeed = -self.actuatorSpeedDefault
    try:
      self.setTargetSpeed(self.actuatorSpeed)
      self.exit_safe_start()

      time.sleep(forTime)

      self.setTargetSpeed(0) #stop movement
      position = self.get_variable(12)
    except Exception as e:
      print(str(e))
      self.setTargetSpeed(0)


  def moveToReset(self):

    print('set reset')
    self.actuatorSpeedDefault = 3200
    self.actuatorSpeed = -self.actuatorSpeedDefault
    try:
      self.setTargetSpeed(self.actuatorSpeed)
      self.exit_safe_start()

#      while True:
      position = self.get_variable(12)
      forTime = position / 370
      print(position, forTime)
#        if(position < 60):
#          break
      time.sleep(forTime)

      self.setTargetSpeed(0) #stop movement

      position = self.get_variable(12)
      print(position)

    except Exception as e:
      print(str(e))
      self.setTargetSpeed(0)


  def setPressure(self, pressure):
    self.pressure = pressure
    self.atPressure = False

  def moveToPressure(self, pressure):

    print('set pressure {}'.format(pressure))
    self.actuatorSpeedDefault = 3000
    self.actuatorSpeed = self.actuatorSpeedDefault
    self.setTargetSpeed(self.actuatorSpeed)
    self.exit_safe_start()

    while(True):

      voltage = 0
      try:
        voltage = 0
      except Exception as e:
        print(str(e))
        self.setTargetSpeed(0)
        break

      pressureBar = ((( voltage - .450) * 200.0 / 4.0)) * 0.0689475729;
#      print(voltage, pressureBar, pressure, self.actuatorSpeed)

#      if(pressureBar < -.02):
#        self.actuatorSpeed = -self.actuatorSpeedDefault
      if(pressureBar < -2000.02):
        self.actuatorSpeed = self.actuatorSpeedDefault
        self.setTargetSpeed(self.actuatorSpeed)
        print('reseting pressure')
        while(pressureBar < 0.02):
           voltage = 0
           try:
             voltage = 0
             pressureBar = ((( voltage - .450) * 200.0 / 4.0)) * 0.0689475729;
           except Exception as e:
             print(str(e))
             self.setTargetSpeed(0)
             break
           time.sleep(0.1)

      if(abs(pressureBar - pressure) < 0.01):
        print('stopped at ', str(pressureBar))
        self.setTargetSpeed(0)
        self.atPressure = True
        break

      if(pressureBar > pressure):
        if(self.actuatorSpeed > 0):
           self.actuatorSpeed = -self.actuatorSpeedDefault
           self.setTargetSpeed(self.actuatorSpeed)
      if(pressureBar < pressure):
        if(self.actuatorSpeed < 0):
           self.actuatorSpeed = self.actuatorSpeedDefault
           self.setTargetSpeed(self.actuatorSpeed)
#           print(voltage, pressureBar, pressure, self.actuatorSpeed)

      time.sleep(0.001)

  # Sends the Exit Safe Start command, which is required to drive the motor.
  def exit_safe_start(self):
    write = i2c_msg.write(self.address, [0x83])
    self.bus.i2c_rdwr(write)
 
  # Sets the SMC's target speed (-3200 to 3200).
  def setTargetSpeed(self, speed):
    cmd = 0x85  # Motor forward
    if speed < 0:
      cmd = 0x86  # Motor reverse
      speed = -speed

    buffer = [cmd, speed & 0x1F, speed >> 5 & 0x7F]
    write = i2c_msg.write(self.address, buffer)
    time.sleep(0.1)
    self.bus.i2c_rdwr(write)
 
  # Gets the specified variable as an unsigned value.
  def get_variable(self, id):
    write = i2c_msg.write(self.address, [0xA1, id])
    read = i2c_msg.read(self.address, 2)
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
 
'''
target_speed = smc.get_target_speed()
print("Target speed is {}.".format(target_speed))
 
new_speed = 3200 if target_speed <= 0 else -3200
print("Setting target speed to {}.\n".format(new_speed));
smc.set_target_speed(new_speed)
'''