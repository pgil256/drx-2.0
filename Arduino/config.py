import configparser
import serial
import time
from datetime import datetime
import os
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QInputDialog, QLineEdit, QFileDialog
from PyQt5 import QtCore, QtGui, QtWidgets

class Configuration():
    def getList(option, sep=',', chars=None):
       return [ chunk.strip(chars) for chunk in option.split(sep) ]

    def __init__(self):

       self.flexionPosition = 0
       self.CFactor = 1900

    def getConfig(self):
     
       self.config = configparser.ConfigParser(allow_no_value=True)
       self.configFile = "kneespa.cfg"
         # Load configuration

       if not os.path.exists(self.configFile):
         self.config['Options'] = {'flexionPosition':self.flexionPosition}
         self.config.write(open(self.configFile, 'w'))
       else:
     
        try:
          self.config.read(self.configFile)

          allSections = {s:dict(self.config.items(s)) for s in self.config.sections()}
          self.AMarks = allSections['AMarks']
          self.BMarks = allSections['BMarks']
          self.CMarks = allSections['CMarks']
          print(self.BMarks)
          section = 'Options'

          if(not self.config.has_section(section)):
             self.config.add_section(section)

          if(not self.config.has_option(section, 'flexionPosition')):
             self.config.set('Options', 'flexionPosition', str(self.flexionPosition))
          else:
             self.flexionPosition = int(self.config['Options']['flexionPosition'])

          if(not self.config.has_option(section, 'AFactor')):
             self.config.set('Options', 'AFactor', str(self.AFactor))
          else:
             self.AFactor = int(self.config['Options']['AFactor'])

          if(not self.config.has_option(section, 'BFactor')):
             self.config.set('Options', 'BFactor', str(self.BFactor))
          else:
             self.BFactor = int(self.config['Options']['BFactor'])

          if(not self.config.has_option(section, 'CFactor')):
             self.config.set('Options', 'CFactor', str(self.CFactor))
          else:
             self.CFactor = int(self.config['Options']['CFactor'])

          if(not self.config.has_option(section, 'unlock')):
             self.config.set('Options', 'unlock', str(self.unlock))
          else:
             self.unlock = self.config['Options']['unlock']

          if(not self.config.has_option(section, 'calibration')):
             self.config.set('Options', 'calibration', str(self.calibration))
          else:
             self.calibration = float(self.config['Options']['calibration'])

        except Exception as e:
           print(str(e))
           print('Fatal error, could not load config file from "%s"' % self.configFile)


    def updateConfig(self):
       section = 'Options'
       print(self.flexionPosition)
       self.config.set('Options', 'flexionPosition', str(self.flexionPosition))

       self.config.set('Options', 'CFactor', str(self.CFactor))
       self.config.set('Options', 'BFactor', str(self.BFactor))
       self.config.set('Options', 'CFactor', str(self.CFactor))

       self.config.set('Options', 'unlock', str(self.unlock))
       self.config.set('Options', 'calibration', str(self.calibration))

       print('config written')
       try:
         self.config.write(open(self.configFile, 'w'))
       except Exception as e:
           print(str(e))
           print('Fatal error, could not load config file from "%s"' % self.configFile)
