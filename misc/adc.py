# Import the ADS1x15 module.
import Adafruit_ADS1x15


class ADC():

  A0 = 0
  GAIN = 1

  def __init__(self, address=12 ):

# Create an ADS1115 ADC (16-bit) instance.
    self.adc = Adafruit_ADS1x15.ADS1115(address)

  def getValue(self):
     value = self.adc.read_adc(self.A0, gain=self.GAIN)
     return value