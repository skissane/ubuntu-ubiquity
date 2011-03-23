#!/usr/bin/python


import unittest
# These tests require Mock 0.7.0
import mock
from test import test_support
import sys
import os
sys.path.insert(0, 'ubiquity/plugins')
ubi_partman = __import__('ubi-partman')
sys.path.pop()
from ubiquity import misc
import debconf

# These tests skip when their dependencies are not met and tests/run takes
# arguments to generate said dependencies, so neither need to know about the
# inner workings of each other.

@unittest.skipUnless(os.path.exists('tests/partman-tree'), 'Need /lib/partman.')
class PartmanPageDirectoryTests(unittest.TestCase):
    def setUp(self):
        # We could mock out the db for this, but we ultimately want to make
        # sure that the debconf questions its getting exist.
        self.page = ubi_partman.Page(None)
        self.page.db = debconf.DebconfCommunicator('ubi-test', cloexec=True)
        self.addCleanup(self.page.db.shutdown)

        prefix = 'tests/partman-tree'
        def side_effect_factory(real_method):
            def side_effect(path, *args, **kw):
                if path.startswith('/lib/partman'):
                    return real_method('%s%s' % (prefix, path), *args, **kw)
                else:
                    return real_method(path, *args, **kw)
            return side_effect

        for method in ('listdir', 'path.isdir', 'access', 'path.exists'):
            if method.startswith('path'):
                real_method = getattr(os.path, method.split('.')[1])
            else:
                real_method = getattr(os, method)
            method = mock.patch('os.%s' % method)
            mocked_method = method.start()
            mocked_method.side_effect = side_effect_factory(real_method)
            self.addCleanup(method.stop)

        self.page.description_cache = {}

    def test_method_description(self):
        for method in self.page.subdirectories('/lib/partman/choose_method'):
            print method

@unittest.skipUnless('DEBCONF_SYSTEMRC' in os.environ, 'Need a database.')
class TestPage(unittest.TestCase):
    def setUp(self):
        # We could mock out the db for this, but we ultimately want to make
        # sure that the debconf questions its getting exist.
        self.page = ubi_partman.Page(None)
        self.page.db = debconf.DebconfCommunicator('ubi-test', cloexec=True)
        self.addCleanup(self.page.db.shutdown)

        # We don't want to go through the entire prepare method, pulling
        # in fakeroot, just to intialize description_cache.
        self.page.description_cache = {}

    def test_description(self):
        question = 'partman-auto/init_automatically_partition'
        description = unicode(self.page.db.metaget(question, 'description'),
                              'utf-8', 'replace')
        self.assertEqual(self.page.description(question), description)
        self.assertIn(question, self.page.description_cache)

    def test_default_mountpoint_choices(self):
        pairs = [('partman-basicfilesystems/fat_mountpoint', 'ntfs'),
                 ('partman-basicfilesystems/mountpoint', 'ext4')]
        try:
            # We cannot test uboot if we're not running on armel.
            self.page.description('partman-uboot/mountpoint')
            pairs.append(('partman-uboot/mountpoint', 'uboot'))
        except debconf.DebconfError:
            pass
        for question, fs in pairs:
            choices = self.page.choices_untranslated(question)
            mountpoints = [choice.split(' ', 1)[0] for choice in choices
                           if choice.startswith('/')]
            default_mountpoints = [default[0] for default in
                                   self.page.default_mountpoint_choices(fs)]
            self.assertTrue(len(default_mountpoints) > 0)
            self.assertItemsEqual(mountpoints, default_mountpoints)

    def test_method_description(self):
        # FIXME: move this into the Directory tests, following use_as()
        pairs = [('swap', 'partman/method_long/swap'),
                 ('efi', 'partman-efi/text/efi'),
                 ('biosgrub', 'partman/method_long/biosgrub')]
        try:
            # We cannot test newworld if we're not running on powerpc.
            self.page.description('partman/method_long/newworld')
            pairs.append(('newworld', 'partman/method_long/newworld'))
        except debconf.DebconfError:
            pass
        for method, question in pairs:
            self.assertEqual(self.page.description(question),
                             self.page.method_description(method))
        self.assertEqual(self.page.method_description('foobar'), 'foobar')


@unittest.skipUnless('DEBCONF_SYSTEMRC' in os.environ, 'Need a database.')
class TestCalculateAutopartitioningOptions(unittest.TestCase):
    '''Test that the each expected autopartitioning option exists and is
       worded properly.'''

    def setUp(self):
        # We could mock out the db for this, but we ultimately want to make
        # sure that the debconf questions its getting exist.
        self.page = ubi_partman.Page(None)
        self.page.db = debconf.DebconfCommunicator('ubi-test', cloexec=True)
        self.addCleanup(self.page.db.shutdown)

        find_in_os_prober = mock.patch('ubiquity.misc.find_in_os_prober')
        find_in_os_prober.start()
        self.addCleanup(find_in_os_prober.stop)

        get_release = mock.patch('ubiquity.misc.get_release')
        get_release.start()
        self.addCleanup(get_release.stop)

        # We don't want to go through the entire prepare method, pulling
        # in fakeroot, just to intialize description_cache.
        self.page.description_cache = {}

        # Always checked, never SUBST'ed.
        question = 'ubiquity/partitioner/advanced'
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        self.manual = ubi_partman.PartitioningOption(title, desc)

    # 'This computer currently has Windows on it.'
    def test_windows_only(self):
        operating_system = u'Windows XP'
        misc.find_in_os_prober.return_value = operating_system
        release = misc.ReleaseInfo('Ubuntu', '11.04')
        misc.get_release.return_value = release
        part = ubi_partman.Partition('/dev/sda1', 0, '1234-1234', 'ntfs')
        layout = { '=dev=sda' : [part] }
        self.page.extra_options = {}
        self.page.extra_options['resize'] = {
            '=dev=sda' : [ '', 0, 0, 0, '', 0, 'ntfs']}

        question = 'ubiquity/partitioner/single_os_resize'
        # Ensure that we're not grabbing the value from previous runs.
        self.page.db.subst(question, 'DISTRO', release.name)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        resize = ubi_partman.PartitioningOption(title, desc)

        question = 'ubiquity/partitioner/single_os_replace'
        self.page.db.subst(question, 'OS', operating_system)
        self.page.db.subst(question, 'DISTRO', release.name)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        replace = ubi_partman.PartitioningOption(title, desc)

        operating_systems, ubuntu_systems = \
            self.page.calculate_operating_systems(layout)
        options = self.page.calculate_autopartitioning_options(
                        operating_systems, ubuntu_systems)
        self.assertIn('resize', options)
        self.assertItemsEqual(resize, options['resize'])
        self.assertIn('use_device', options)
        self.assertItemsEqual(replace, options['use_device'])
        self.assertIn('manual', options)
        self.assertItemsEqual(self.manual, options['manual'])

    # 'This computer currently has no operating systems on it.'
    def test_empty(self):
        self.page.extra_options = {}
        self.page.extra_options['use_device'] = ('debconf-return-value',
                                                 [{'disk-desc': 0}])
        release = misc.ReleaseInfo('Ubuntu', '11.04')
        misc.get_release.return_value = release

        question = 'ubiquity/partitioner/no_systems_format'
        self.page.db.subst(question, 'DISTRO', release.name)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        use_device = ubi_partman.PartitioningOption(title, desc)
        operating_systems, ubuntu_systems = \
            self.page.calculate_operating_systems([])
        options = self.page.calculate_autopartitioning_options(
                        operating_systems, ubuntu_systems)

        self.assertIn('use_device', options)
        self.assertItemsEqual(use_device, options['use_device'])

        self.assertIn('manual', options)
        self.assertItemsEqual(self.manual, options['manual'])

    # 'This computer currently has Ubuntu 10.04 on it.'
    def test_older_ubuntu_only(self):
        operating_system = u'Ubuntu 10.04'
        misc.find_in_os_prober.return_value = operating_system
        release = misc.ReleaseInfo('Ubuntu', '11.04')
        misc.get_release.return_value = release
        part = ubi_partman.Partition('/dev/sda1', 0, '1234-1234', 'ext4')
        layout = { '=dev=sda' : [part] }
        self.page.extra_options = {}
        self.page.extra_options['use_device'] = ('debconf-return-value',
                                                 [{'disk-desc': 0}])
        self.page.extra_options['reuse'] = [(0, '/dev/sda1')]

        question = 'ubiquity/partitioner/ubuntu_format'
        self.page.db.subst(question, 'CURDISTRO', operating_system)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        use_device = ubi_partman.PartitioningOption(title, desc)

        question = 'ubiquity/partitioner/ubuntu_upgrade'
        self.page.db.subst(question, 'CURDISTRO', operating_system)
        self.page.db.subst(question, 'VER', release.version)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        reuse = ubi_partman.PartitioningOption(title, desc)

        operating_systems, ubuntu_systems = \
            self.page.calculate_operating_systems(layout)
        options = self.page.calculate_autopartitioning_options(
                        operating_systems, ubuntu_systems)
        self.assertIn('use_device', options)
        self.assertItemsEqual(use_device, options['use_device'])

        self.assertIn('manual', options)
        self.assertItemsEqual(self.manual, options['manual'])

        self.assertIn('reuse', options)
        self.assertItemsEqual(reuse, options['reuse'])

    # 'This computer currently has Ubuntu 11.04 on it.'
    @unittest.skipIf(True, 'functionality currently broken.')
    def test_same_ubuntu_only(self):
        operating_system = u'Ubuntu 11.04'
        misc.find_in_os_prober.return_value = operating_system
        release = misc.ReleaseInfo('Ubuntu', '11.04')
        misc.get_release.return_value = release
        part = ubi_partman.Partition('/dev/sda1', 0, '1234-1234', 'ext4')
        layout = { '=dev=sda' : [part] }
        self.page.extra_options = {}
        self.page.extra_options['use_device'] = ('debconf-return-value',
                                                 [{'disk-desc': 0}])
        self.page.extra_options['reuse'] = [(0, '/dev/sda1')]

        question = 'ubiquity/partitioner/ubuntu_format'
        self.page.db.subst(question, 'CURDISTRO', operating_system)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        use_device = ubi_partman.PartitioningOption(title, desc)

        question = 'ubiquity/partitioner/ubuntu_reinstall'
        self.page.db.subst(question, 'CURDISTRO', operating_system)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        reuse = ubi_partman.PartitioningOption(title, desc)

        operating_systems, ubuntu_systems = \
            self.page.calculate_operating_systems(layout)
        options = self.page.calculate_autopartitioning_options(
                        operating_systems, ubuntu_systems)
        self.assertIn('use_device', options)
        self.assertItemsEqual(use_device, options['use_device'])

        self.assertIn('manual', options)
        self.assertItemsEqual(self.manual, options['manual'])

        self.assertIn('reuse', options)
        self.assertItemsEqual(reuse, options['reuse'])

    # 'This computer currently has multiple operating systems on it.'
    def test_multiple_operating_systems(self):
        operating_systems = [u'Ubuntu 10.04', u'Windows XP', u'Mac OSX']
        def side_effect(*args, **kwargs):
            return operating_systems.pop()
        misc.find_in_os_prober.side_effect = side_effect
        release = misc.ReleaseInfo('Ubuntu', '11.04')
        misc.get_release.return_value = release
        part1 = ubi_partman.Partition('/dev/sda1', 0, '1234-1234', 'ext4')
        part2 = ubi_partman.Partition('/dev/sda2', 0, '1234-1234', 'ext4')
        part3 = ubi_partman.Partition('/dev/sda3', 0, '1234-1234', 'ext4')
        layout = { '=dev=sda' : [part1, part2, part3] }
        self.page.extra_options = {}
        self.page.extra_options['use_device'] = ('debconf-return-value',
                                                 [{'disk-desc': 0}])
        self.page.extra_options['resize'] = {
            '=dev=sda' : [ '', 0, 0, 0, '', 0, 'ntfs']}

        question = 'ubiquity/partitioner/multiple_os_format'
        self.page.db.subst(question, 'DISTRO', release.name)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        use_device = ubi_partman.PartitioningOption(title, desc)

        question = 'ubiquity/partitioner/multiple_os_resize'
        self.page.db.subst(question, 'DISTRO', release.name)
        title = self.page.description(question)
        desc = self.page.extended_description(question)
        resize = ubi_partman.PartitioningOption(title, desc)

        operating_systems, ubuntu_systems = \
            self.page.calculate_operating_systems(layout)
        options = self.page.calculate_autopartitioning_options(
                        operating_systems, ubuntu_systems)
        self.assertIn('use_device', options)
        self.assertItemsEqual(use_device, options['use_device'])

        self.assertIn('resize', options)
        self.assertItemsEqual(resize, options['resize'])

        self.assertIn('manual', options)
        self.assertItemsEqual(self.manual, options['manual'])

if __name__ == '__main__':
    test_support.run_unittest(TestCalculateAutopartitioningOptions, TestPage, PartmanPageDirectoryTests)
