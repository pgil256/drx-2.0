# -*- coding: utf-8 -*-
"""

@author: grimesr
"""
from datetime import datetime
import time
import threading


from PyQt5 import QtCore
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt5.QtCore import pyqtSlot


class WorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        tuple (exctype, value, traceback.format_exc() )

    result
        object data returned from processing, anything

    progress
        int indicating % progress

    '''
    finished = pyqtSignal(bool)
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    APressure = pyqtSignal(str)
    progress = pyqtSignal(str)

'''
     degrees vs distance
      0 5" extended (will hold here and return)
      5 4" extended (will hold here and return)
     10 3" extended (will hold here and return)
     15 2"
     20 1"
     25 0"
     30 Full retract
'''
DEGREES0 = 0
DEGREES5 = 5
DEGREES10 = 10
DEGREES15 = 15

NOWEIGHT = 0
STARTWEIGHT =  5
STARTPOSITION = 0.5

class Arduino(QObject):
   finished = pyqtSignal(bool)
   progress = pyqtSignal(int)
   doneEmit = pyqtSignal()

   def __init__(self):
      super(Arduino, self).__init__()
      print('init com')

   def run(self):

      print('startSerial')

      try:
        self.serialCOM1 = serial.Serial('/dev/ttyS0', 115200, timeout=10, write_timeout=1)
        time.sleep(2)
        print(self.serialCOM1)
        self.connected = True
      except Exception as ex:
         print(str(ex))

      print('Inited')

      self.readFromCOM1(self.serialCOM1)

   def handleCOM1(self, ser, data):

       tokens = data.split('|')
       print(tokens)
       if(tokens[0] == 'DONE'):
          self.doneEmit.emit()

   def readFromCOM1(self, ser):
      global startRun
      while True:
        try:
          reading = ser.readline().decode().strip()
#          print(reading)
          if(len(reading) > 0):
            self.handleCOM1(ser, reading)
        except Exception as ex:
          print(str(ex))

        time.sleep(0.1)


   def send(self, command):

     command += '\n'
     print('cmd {}'.format(command.strip()))
     self.serialCOM1.write(command.encode())                #transmit data serially 
     self.serialCOM1.flush()


class KeepPressure(QtCore.QRunnable):
   def __init__(self, pressure, parent=None):
     super(KeepPressure, self).__init__()

     self.pressure = pressure

     self.running = False

   @pyqtSlot()
   def run(self):
     print("Pressure Thread start")
     self.running = True

   def stop(self):
     print('Pressure stop')
     self.running = False

#     self.setToPressure(self.pressure)

   def setToPressure(self, desiredPressure):

     while self.running:
       command = 'I{}'.format(12)
       self.arduino.send(command)                #transmit data serially 

       command = 'P{}'.format(desiredPressure)
       self.arduino.send(command)                #transmit data serially 
       print('cmd {}'.format(command.strip()))

       time.sleep(0.5)

     print('end')

 
class Protocols(QtCore.QRunnable):
   progress = pyqtSignal(str)
   completed = pyqtSignal()

   protocol = ''
   pressure = 0
   cycles = 0

   protocolList = ['S', 'B1', 'B2', 'B3', 'B0']
   def __init__(self, _BFactor, protocol, degrees, startDegrees, cycles, ser, parent=None):
#     QThread.__init__(self, parent)
     super(Protocols, self).__init__()

     self.arduino = ser

     self.BFactor = _BFactor

     self.signals = WorkerSignals()

     self.isRunning = False

     self.degreeList = {0:5, 5:4, 10:3, 15:2, 20:1, 25:0, 30:0}

     self.I2Cstatus = 0

     self.protocol = protocol
     self.degrees = degrees
     self.startDegrees = startDegrees
     self.cycles = cycles
     self.startPosition = 0

     print(self.protocol, self.protocolList)
     if(self.protocol not in self.protocolList):
        return
     '''
      # Step 2: Create a QThread object
     self.thread = QThread()
      # Step 3: Create a worker object
     self.arduino = Arduino()
      # Step 4: Move worker to the thread
     self.arduino.moveToThread(self.thread)
      # Step 5: Connect signals and slots
     self.thread.started.connect(self.arduino.run)
     self.arduino.finished.connect(self.thread.quit)
     self.arduino.finished.connect(self.thread.deleteLater)
      # Step 6: Start the thread
     self.thread.start()

     self.arduino.doneEmit.connect(self.setDone)
     '''
#     self.ser = serial.Serial('/dev/ttyS0',115200)
#     self.ser.flush()

     self.isRunning = False
     self.exitFlag = threading.Event()

   @pyqtSlot()
   def run(self):
     print("Thread start")

     self.isRunning = True

     if(self.protocol[0] == 'S'):
       print('setup')
       self.setup()

     if(self.protocol[0] == 'B'):
       self.BProtocol(self.protocol, self.degrees, self.startDegrees, self.cycles)
     print('thread END')
#     self.completed.emit()
#     self.signals.finished.emit(True)  # Done

   def stop(self):
     print('stop')
     self.isRunning = False
     self.exitFlag.set()

     try:
       self.arduino.send('X')                #transmit data serially 
       pass
     except Exception as e:
       print(str(e))

   def status(self, positionA, positionB, steps, pressure):
#     print('>> A {} B {} C {} Pressure {}'.format(positionA, positionB, steps, pressure))
#     self.startPosition = positionA
     self.pressure = pressure
     self.signals.APressure.emit('Pressure at {} lbs'.format(self.pressure))

   def BProtocol(self, protocol, minusDegrees, plusDegrees, cycles):
     print('**** {} degrees -{} +{} cycles {}'.format(protocol, minusDegrees, plusDegrees, cycles))

     print('sendCalibration')
     self.arduino.send('L1')
#     time.sleep(1)
     self.I2Cstatus = 0
     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('stopped')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')

     if(self.setAToDistance(STARTPOSITION) == False):
        self.signals.finished.emit(False)
        return
     self.signals.progress.emit('Moved to start {}'.format(STARTPOSITION))

     if(protocol == 'B1'):
        self.protocol1(minusDegrees, plusDegrees, cycles)
     if(protocol == 'B2'):
        self.protocol2(minusDegrees, plusDegrees, cycles)
     if(protocol == 'B3'):
        self.protocol3(minusDegrees, plusDegrees, cycles)
     if(protocol == 'B0'):
        self.protocol0(minusDegrees, plusDegrees)


   def killProtocol(self):
     self.isRunning = False

   def setup(self):
     inches = self.degreeList[DEGREES10] #set as initial angle
     position = int(inches * self.BFactor / 6.0)
     self.setToDistance(position)
     print(' positioned to {} in.'.format(inches))

   def I2CStatus(self):
     self.I2Cstatus = True

   def setToPosition(self, speed, position):
     pass

   def setToDistance(self, degrees):
     inches = self.degreeList[degrees] #set as initial angle
     position = int(inches * self.BFactor / 6.0)
     print(' positioned to {} deg {} in. {} pos'.format(degrees, inches, position))

     command = 'A13{}'.format(inches)
     self.arduino.send(command)
     print('cmd {}'.format(command.strip()))

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('STOPPED')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def setAToDistance(self, inches):
     print(' positioned to deg {} in.'.format(inches))

     command = 'A12{}'.format(inches)
     self.arduino.send(command)

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('STOPPED')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def setToPressure(self, desiredPressure):
     command = 'P{}'.format(desiredPressure)
     self.arduino.send(command)                #transmit data serially 
     print('cmd {}'.format(command.strip()))

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('stopped')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def resetA(self):
     self.signals.progress.emit('>>Moved to start {} Degrees'.format(DEGREES15))
     if(self.setToDistance(DEGREES15) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES15))

     self.signals.progress.emit('>>Moved to start {}'.format(NOWEIGHT))
     if(self.setAToDistance(NOWEIGHT) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Moved to start {}'.format(NOWEIGHT))
     return True


   def protocol0(self, minusDegrees, plusDegrees):

     self.threadpool = QtCore.QThreadPool()
     print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
#     self.pressureWorker = KeepPressure(3)
 #    self.threadpool.start(self.pressureWorker)

     if(self.setToDistance(degrees) == False):
       self.signals.finished.emit(False)
       return

#     self.pressureWorker.stop()

     self.signals.finished.emit(True)



   def protocol1(self, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Pressure to {} lbs'.format(STARTWEIGHT))
     if(self.setToPressure(STARTWEIGHT) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure to {} lbs'.format(STARTWEIGHT))

     for cycle in range(1, cycles+1):

       for oneCycle in range(2):
         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, plusDegrees))
         if(self.setToDistance(plusDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, plusDegrees))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, minusDegrees))
         if(self.setToDistance(minusDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, minusDegrees))
         self.exitFlag.wait(timeout=3)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')

   def protocol2(self, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Pressure to {} lbs'.format(STARTWEIGHT))
     if(self.setToPressure(STARTWEIGHT) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure to {} lbs'.format(STARTWEIGHT))

     for cycle in range(1, cycles+1):
       print('cycle {}'.format(cycle))

       currentDegrees = plusDegrees
       while(currentDegrees < minusDegrees):
         print('currentDegrees {}:-{} +{}'.format(currentDegrees, minusDegrees, plusDegrees))

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, plusDegrees))
         if(self.setToDistance(plusDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, plusDegrees))
         self.exitFlag.wait(timeout=3)

         currentDegrees += 5

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 5 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 5 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=5)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


   def protocol3(self, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Pressure to {} lbs'.format(STARTWEIGHT))
     if(self.setToPressure(STARTWEIGHT) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure to {} lbs'.format(STARTWEIGHT))

     for cycle in range(1, cycles+1):

       currentDegrees = plusDegrees
       while(currentDegrees <= minusDegrees):
         print('currentDegrees {}:-{} +{}'.format(currentDegrees, minusDegrees, plusDegrees))
         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

         currentDegrees += 5

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


