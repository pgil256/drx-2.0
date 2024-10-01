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

DEGREES0 = 0
DEGREES5 = 5
DEGREES10 = 10
DEGREES15 = 15

POUNDS10 = 10
NOWEIGHT = 0
STARTPOSITION = 0.5

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
    progress = pyqtSignal(str)
    APressure = pyqtSignal(str)
    pressureComplete = pyqtSignal()

'''
     degrees vs distance
      0 0" extended (will hold here and return)
      5 5" extended (will hold here and return)
     10 4" extended (will hold here and return)
     15 3"
     20 2"
     25 1"
     30 Full retract
'''

class Protocols(QtCore.QRunnable):
   progress = pyqtSignal(str)
   completed = pyqtSignal()

   protocol = ''
   pressure = 0
   cycles = 0

   protocolList = ['S', 'AC1', 'AC2', 'AC3', 'AC4', 'AC5', 'AC6', 'AC7', 'AC8', 'AC9', 'AC0']
   def __init__(self, _CFactor, protocol, pressure, leftLatAngle, rightLatAngle, startDegrees, cycles, ser, config, parent=None):
     super(Protocols, self).__init__()

     self.CDegrees = 0.1	#convert degrees to inches

     self.arduino = ser

     self.CFactor = _CFactor
     self.config = config

     self.signals = WorkerSignals()

     self.isRunning = False

     self.degreeList = {1:.025, 5:.625, 10:.75, 15:.875, 20:1, 0:.5, -5:.375, -10:.25, -15:.125, -20:0}

     self.I2Cstatus = 0

     self.protocol = protocol
     self.pressure = pressure
     self.leftLatAngle = leftLatAngle
     self.rightLatAngle = rightLatAngle
     self.startDegrees = startDegrees
     self.cycles = cycles
     self.startPosition = 0

     if(self.protocol not in self.protocolList):
        return

     self.isRunning = False
     self.exitFlag = threading.Event()


   @pyqtSlot()
   def run(self):
#     print("Thread start")

     self.isRunning = True

     if(self.protocol[0] == 'S'):
       print('setup')
       self.setup()

     if(self.protocol[0:2] == 'AC'):
       self.ACProtocol(self.protocol, self.pressure, self.leftLatAngle, self.rightLatAngle, self.startDegrees, self.cycles)
#     print('thread END')
#     self.completed.emit()
#     self.signals.finished.emit(True)  # Done

   def stop(self):
     print('stop')
     self.isRunning = False
     self.exitFlag.set()

     try:
       self.arduino.send('X')                #transmit data serially 
     except Exception as e:
       print(str(e))

   def ACProtocol(self, protocol, pressure, leftLatAngle, rightLatAngle, startDegrees, cycles):
     leftLatAngle = -leftLatAngle
     print('*** {} {}lbs degrees {}/{} start {} cycles {}'.format(protocol, pressure, leftLatAngle, rightLatAngle, startDegrees, cycles))

     print('sendCalibration')
     self.arduino.send('L1')
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

     if(protocol == 'AC1'):
        self.protocol1(pressure, leftLatAngle, startDegrees, cycles)
     if(protocol == 'AC2'):
        self.protocol2(pressure, rightLatAngle, startDegrees, cycles)
     if(protocol == 'AC3'):
        self.protocol3(pressure, leftLatAngle, startDegrees, cycles)
     if(protocol == 'AC4'):
        self.protocol4(pressure, rightLatAngle, startDegrees, cycles)
     if(protocol == 'AC5'):
        self.protocol5(pressure, leftLatAngle, startDegrees, cycles)
     if(protocol == 'AC6'):
        self.protocol6(pressure, rightLatAngle, startDegrees, cycles)
     if(protocol == 'AC7'):
        self.protocol7(pressure, leftLatAngle, startDegrees, cycles)
     if(protocol == 'AC8'):
        self.protocol8(pressure, rightLatAngle, startDegrees, cycles)
     if(protocol == 'AC9'):
        self.protocol9(pressure, leftLatAngle, rightLatAngle, startDegrees, cycles)

   def killProtocol(self):
     self.isRunning = False

   def setup(self):
     inches = self.degreeList[DEGREES10] #set as initial angle
     position = int(inches * self.CFactor / 6.0)


   def pressureDone(self):
     self.stopPressure = True
     print('self.stopPressure = True')

   def I2CStatus(self):
     self.I2Cstatus = True

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

   def setToDistance(self, degrees):
     position = self.config.CMarks['{:.1f}'.format(degrees)]
     print(' positioned to {} degrees pos {}'.format(degrees, position))
     command = 'K{}'.format(position)
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


   def status(self, positionA, positionB, steps, pressure):
#     print('>> A {} B {} C {} Pressure {}'.format(positionA, positionB, steps, pressure))
     self.startPosition = positionA
     self.pressure = pressure
     self.signals.APressure.emit('Pressure at {} lbs'.format(self.pressure))

   def resetA(self):
     self.signals.progress.emit('>>Moved to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return False
     self.signals.progress.emit('Moved to start Degrees'.format(DEGREES0))

     self.signals.progress.emit('>>Moved to start {}'.format(NOWEIGHT))
     if(self.setAToDistance(NOWEIGHT) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Moved to start {}'.format(NOWEIGHT))
     return True


   def protocol0(self, pressure):
     return

     inches = (self.startPosition  * 6.0)/ self.CFactor
     print('A Position {} Pressure {} lbs {:.2f} inches'.format(self.startPosition, self.pressure, inches))

     self.signals.progress.emit('A Positioned at {:.1f} in. for start.'.format(inches))
     self.signals.finished.emit(True)


   def protocol1(self, pressure, leftLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start Degrees'.format(DEGREES0))

     for cycle in range(1, cycles+1):

       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False
       
       while(inLoop):
         if(currentPressure + 4 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 4

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentDegrees - 2.5 <= leftLatAngle):
           currentDegrees = leftLatAngle
           outLoopB = True
         else:
           currentDegrees -= 2.5

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA and outLoopB)
         print(inLoop, outLoopA, outLoopB)

       self.signals.progress.emit('Cycle {} hold 5 secs'.format(cycle))
       self.exitFlag.wait(timeout=5)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


   def protocol2(self, pressure, rightLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES0))

     for cycle in range(1, cycles+1):

       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False

       while(inLoop):
         if(currentPressure + 4 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 4

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         if(currentDegrees + 2.5 > rightLatAngle):
           currentDegrees = rightLatAngle
           outLoopB = True
         else:
           currentDegrees += 2.5

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA and outLoopB)
         print(inLoop, outLoopA, outLoopB)

       self.signals.progress.emit('Cycle {} hold 5 secs'.format(cycle))
       self.exitFlag.wait(timeout=5)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')



   def protocol3(self, pressure, leftLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start Degrees'.format(DEGREES0))

     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False

       while(inLoop):
         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentDegrees - 2.5 <= leftLatAngle):
           currentDegrees = leftLatAngle
           outLoopB = True
         else:
           currentDegrees -= 2.5

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA and outLoopB)
         print(inLoop, outLoopA, outLoopB)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')



   def protocol4(self, pressure, rightLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES0))

     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False

       while(inLoop):
         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         if(currentDegrees + 2.5 > rightLatAngle):
           currentDegrees = rightLatAngle
           outLoopB = True
         else:
           currentDegrees += 2.5

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA and outLoopB)
         print(inLoop, outLoopA, outLoopB)

       self.signals.progress.emit('Cycle {} hold 5 secs'.format(cycle))
       self.exitFlag.wait(timeout=5)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')



   def protocol5(self, pressure, leftLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES0))

     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False

       while(inLoop):
         currentPressure -= 1

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentPressure + 4 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 4

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)



         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, leftLatAngle))
         if(self.setToDistance(leftLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, leftLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA)
         print(inLoop, outLoopA)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


   def protocol6(self, pressure, rightLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES0))

     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False

       while(inLoop):
         currentPressure -= 1

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentPressure + 4 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 4

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)



         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         if(self.setToDistance(rightLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA)
         print(inLoop, outLoopA)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')

   def protocol7(self, pressure, leftLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES0))

     currentPressure = 3
     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False


       while(inLoop):
         currentPressure -= 1

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, -leftLatAngle))
         if(self.setToDistance(leftLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, -leftLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA)
         print(inLoop, outLoopA)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')




   def protocol8(self, pressure, rightLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start {} Degrees'.format(DEGREES0))

     currentPressure = 3
     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, POUNDS10))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False
       outLoopB = False

       while(inLoop):
         currentPressure -= 1

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         if(self.setToDistance(rightLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)

         inLoop = not (outLoopA)
         print(inLoop, outLoopA)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


   def protocol9(self, pressure, leftLatAngle, rightLatAngle, startDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to start Degrees'.format(DEGREES0))

     currentPressure = POUNDS10
     for cycle in range(1, cycles+1):
       currentPressure = POUNDS10
       currentDegrees = DEGREES0

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       inLoop = True
       outLoopA = False

       while(inLoop):
         currentPressure -= 1

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         if(outLoopA):
           break

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 5 secs'.format(cycle, -leftLatAngle))
         if(self.setToDistance(leftLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 5 secs'.format(cycle, -leftLatAngle))
         self.exitFlag.wait(timeout=5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)


         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         if(self.setToDistance(rightLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)


         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         if(outLoopA):
           break

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         currentPressure -= 1

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 3 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=3)

         if(currentPressure + 6 > pressure):
            currentPressure = pressure
            outLoopA = True
         else:
            currentPressure += 6

         if(outLoopA):
           break

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, -leftLatAngle))
         if(self.setToDistance(leftLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, -leftLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)


         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         if(self.setToDistance(rightLatAngle) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
         self.exitFlag.wait(timeout=3)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         if(self.setToDistance(DEGREES0) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
         self.exitFlag.wait(timeout=3)

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, -leftLatAngle))
       if(self.setToDistance(leftLatAngle) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, -leftLatAngle))
       self.exitFlag.wait(timeout=3)

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
       if(self.setToDistance(DEGREES0) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
       self.exitFlag.wait(timeout=3)

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
       if(self.setToDistance(rightLatAngle) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, rightLatAngle))
       self.exitFlag.wait(timeout=3)

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
       if(self.setToDistance(DEGREES0) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, DEGREES0))
       self.exitFlag.wait(timeout=3)


     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')

   def setI2CStatus(self, channel):
      self.I2Cstatus = 1
      print('self.I2Cstatus = 1')

