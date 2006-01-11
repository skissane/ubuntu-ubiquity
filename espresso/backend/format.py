#!/usr/bin/python
# -*- coding: utf-8 -*-

from espresso import misc

class Format:

  def __init__(self, mountpoints):
    """Initial attributes."""

    self.mountpoints = mountpoints


  def format_target (self, queue):
    '''format_target(queue) -> bool

    From mountpoints extract the devices to partition 
    and do it.
    The method return true or false depends the result
    of this operation.
    '''

    for device, path in self.mountpoints.items():
      if path in ['/']:
        queue.put( "1 Formatting root partition" )
        if not misc.ex('mkfs.ext3', device):
          return False
        queue.put( "2 Root partition formatted" )
      elif path == 'swap':
        queue.put( "3 Preparing swap partition" )
        if not misc.ex('mkswap', device):
          return False
        queue.put( "3 Swap partition prepared" )

if __name__ == '__main__':
  mountpoints = misc.get_var()['mountpoints']
  format_target(mountpoints)

# vim:ai:et:sts=2:tw=80:sw=2:
