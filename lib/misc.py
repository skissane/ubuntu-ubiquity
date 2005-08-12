#!/usr/bin/python

def grub_dev(dev):
	leter = {'a': '0', 'b': '1', 'c': '2', 'd': '3', 'e': '4',
		 'f': '5', 'g': '6', 'h': '7', 'i': '8'}
	num   = {'1': '0', '2': '1', '3': '2', '4': '3', '5': '4',
		 '6': '5', '7': '6', '8': '7', '9': '8'}

	ext = dev[7:]
	name = 'hd%s,%s' % (leter[ext[0]], num[ext[1:]])
	return name

def make_yaboot_header(target):
	#FIXME: Finish this function. Maybe call yaboot_installer
	yaboot_conf = open(target + '/etc/yaboot.conf', 'w')
	ofpath = 
	timeout = 100
	yaboot_conf.write('''
## yaboot.conf generated by the Ubuntu installer
##
## run: "man yaboot.conf" for details. Do not make changes until you have!!
## see also: /usr/share/doc/yaboot/examples for example configurations.
##
## For a dual-boot menu, add one or more of:
## bsd=/dev/hdaX, macos=/dev/hdaY, macosx=/dev/hdaZ

device=%s
partition=%s
root=%s
timeout=%s
install=%s
magicboot=/usr/lib/yaboot/ofboot
enablecdboot

''' % (ofpath, partnr, root, timeout, yaboot_location)
