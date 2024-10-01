#  Raspberry Pi Master for Arduino Slave
#  i2c_master_pi.py
#  Connects to Arduino via I2C
  
#  DroneBot Workshop 2019
#  https://dronebotworkshop.com

from smbus import SMBus
import time
import serial


ser=serial.Serial('/dev/ttyS0',38400)
ser.flush()

print ("Enter 1 for ON or 0 for OFF")
while True:
    command = input('command:')
    ser.write(command.encode())                #transmit data serially 

    if ser.in_waiting > 0:
      received_data = ser.readline()              #read serial port
      sleep(0.03)
      data_left = ser.inWaiting()             #check for remaining byte
      received_data += ser.read(data_left)
      print (received_data)                   #print received data
