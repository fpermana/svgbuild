#!/usr/bin/python

import PythonMagick
from PyQt4 import QtCore
from lxml import etree
from Settings import Settings
import Utils
import interpolations
import vectors ; from vectors import *
import time
import os
import shutil
import re

class Camera(QtCore.QObject):
    printText = QtCore.pyqtSignal(QtCore.QString)
    canceled = QtCore.pyqtSignal()
    isRunning = True

    def __init__(self, options):
        super(Camera, self).__init__()
        '''Construct a virtual camera.'''
        self.locked = False
        self.time = 0
        self.area = [ 0., 0., 1., 1. ]
        self.temp = options['folder'] + '/' + options['temp']
        self.width = float(options['width'])
        self.height = float(options['height'])
        #self.dally = options['dally']
        #self.dolly = options['Dolly']
        #self.scale = options['zoom']
        self.options = options
        self.layout = { }
        
    def stopped(self):
        print 'camera stopped'
        self.setIsRunning(False)

    def setIsRunning(self,  isRunning):
        self.isRunning = isRunning
        
    def _write(self, svg):
        # Save a scratch prepared copy of the xml to be used by Inkscape
        file = open(self.temp, 'w')
        file.write(etree.tostring(svg.root, pretty_print=True))
        file.close()

#        file = open('%d.svg' % (self.time), 'w')
#        file.write(etree.tostring(svg.root, pretty_print=True))
#        file.close()

    def survey(self, svg):
        '''Learn the locations of all elements.'''
        if self.layout: return
        self._write(svg)
        # ask Inkscape for a survey of all ids
        settings = ' '.join( [ '-z',
                               '--query-all',
                               ] )
                               
        
        command = ' '.join( [ str(Settings.inkscape), str(settings), str(self.temp) ] )
        #command = ' '.join( [ self.settings.inkscape, settings, self.temp ] )
        #command = QString('%1 %2 %3').arg(Settings.inkscape,).arg(settings).arg(self.temp)
        #print command
        result = Utils.qx(command)
        result = result.split('\n')
        layout = self.layout
        
        page = [ float(svg.root.attrib['width']),
                 float(svg.root.attrib['height']) ]
        for line in result:
            fields = line.split(',')
            if len(fields) != 5: continue
            area = [ float(x) for x in fields[1:] ]
            area[2] += area[0]
            area[3] += area[1]
            layout[fields[0]] = self._flip(area, page)

        self.limit = max(page) / self.options['zoom']
        element_location_count = len(layout.keys())
        self.printText.emit('Surveyed %d element locations.' % element_location_count)

        return element_location_count

    def _flip(self, area, page):
        # Helper to turn --query-all rects into rendering area rects.
        flipped = list(area[:])
        high = abs(area[3]-area[1])
        flipped[1] = page[1] - min(area[1],area[3]) - high
        flipped[3] = flipped[1] + high
        if flipped[2] < flipped[0]:
            flipped[0],flipped[2] = flipped[2],flipped[0]
        return flipped
        
    def locate(self, target):
        '''Find a target (element id or area rect) and convert it
        as necessary to return the area rect.
        '''
        area = None
        if isinstance(target, list):
            area = target
        elif target in self.layout:
            area = self.layout[target]
        return area
        
    def move(self, target):
        '''Find a target (element id or area rect) and move camera
        to view it instantly.
        '''
        area = self.locate(target)
        if area:
            self.area = area
        return area
    
    def _extent(self, target, fill=False):
        # Adjusts a target area to match the camera's proper aspect ratio.
        area = self.locate(target)
        if area[3] == area[1]:
            area[3] += 1
        high = float(area[3]-area[1])
        wide = float(area[2]-area[0])
        ratio = wide / high
        shape = self.width / self.height
        if (ratio > shape) == fill:
            mid = float(area[2]+area[0])/2.
            wide = high * shape
            area[0] = mid - wide/2.
            area[2] = mid + wide/2.
        else:
            mid = float(area[3]+area[1])/2.
            high = wide / shape
            area[3] = mid + high/2.
            area[1] = mid - high/2.
        return area

    def fill(self, target):
        '''Adjust an area to ensure its center fills the camera's view.'''
        return self._extent(target, fill=True)

    def fit(self, target):
        '''Adjust an area to ensure it fits within the camera's view.'''
        return self._extent(target, fill=False)
        
    def zoom(self, target, amount=1.0):
        '''Given a target area rect, ensure the area is not too small.'''
        area = self.locate(target)
        if area[3] == area[1]:
            area[3] += 1
        high = float(area[3]-area[1])
        wide = float(area[2]-area[0])
        ratio = wide / high
        if high < self.limit:
            high = self.limit
            wide = high * ratio
        mid = float(area[2]+area[0])/2.
        wide *= amount
        area[0] = mid - wide/2.
        area[2] = mid + wide/2.
        mid = float(area[3]+area[1])/2.
        high *= amount
        area[3] = mid + high/2.
        area[1] = mid - high/2.
        return area
    
    def speed(self, before, after,  svg = None):
        '''Given two rectangles, calculate how many frames
        of animation to spend on a nice swoop from one to the other.
        Number of frames is bounded.
        '''
        page = [ float(svg.root.attrib['width']),
                 float(svg.root.attrib['height']) ]
        before = V( (before[2]+before[0])/2.,
                    (before[3]+before[1])/2. )
        after = V( (after[2]+after[0])/2.,
                   (after[3]+after[1])/2. )
        dist = vectors.distance(before, after)
        ts = int(interpolations.linear( 0, max(page),
                                        dist,
                                        self.options['dally'], self.options['dolly'] ))
        ts = min(max(self.options['dally'], ts), self.options['dolly'])
        return ts
    
    def shoot(self, svg, marker='>'):
        if not self.isRunning: return
        
        '''Render one image at the current camera position.'''
        # Includes two hacks (spill and convert -extent)
        # to fix imprecise image output sizes.
        # Also applies background color to avoid alpha movie problems.
        if self.options['from'] <= self.time <= self.options['until']:
            time.sleep(0.250)
            self._write(svg)
            output = str("%s/%s%05d.png" % (self.options['folder'],
                                        self.options['name'],
                                        self.time))

            settings = ''
            conversion = ''

            area = None
            camera_file = None
            camera_image = None

            if self.options['page']:
                if self.options['camera']:
                    spill = (self.area[3]-self.area[1]) / 20.
                    area = "%d:%d:%d:%d" % (self.area[0],
                                            self.area[1],
                                            self.area[2],
                                            self.area[3] + spill)

                    camera_file = str("%s/camera%05d.png" % (self.options['folder'], self.time))

                    settings = ' '.join( [ '-z',
                                       '--export-png=%s' % camera_file,
                                       '--export-area=%s' % area,
                                        ])
                    command = ' '.join( [ str(Settings.inkscape), str(settings), str(self.temp) ] )
                    results = Utils.qx(command)

                    camera_image = PythonMagick.Image(camera_file)
                    camera_size = [camera_image.size().width(), camera_image.size().width()]

#                    settings = ' '.join( [ '-format %wx%h',
#                                        ])
#                    command = ' '.join( [ identify, settings, camera_file ] )
#                    camera_size = qx(command)
#                    camera_size = re.sub("[\r\n]*$","", camera_size).split('x')

                    camera_image = PythonMagick.Image('%dx%d' % (camera_size[0], camera_size[1]), '%s' % str(self.options['background']))

                    width = (float(camera_size[0]) + float(camera_size[1])) / float(camera_size[1])

#                    settings = ' '.join( [ '-size %dx%d' % (int(camera_size[0]), int(camera_size[1])),
#                                        'xc:%s' % options['Background']
#                                        ])
#                    command = ' '.join( [ convert, settings, camera_file ] )
#                    results = qx(command)

                    camera_image.borderColor('%s' % str(self.options['frame']))
                    camera_image.border('%dx%d' % (width, width))
                    camera_image.transparent('%s' % str(self.options['background']))

                    camera_image.write(camera_file)

#                    settings = ' '.join( [ '-bordercolor %s' % options['line'],
#                                        '-border %d' % width,
#                                        '-transparent %s' % options['Background']
#                                        ])
#                    command = ' '.join( [ convert, camera_file, settings, camera_file ] )
#                    results = qx(command)

                settings = ' '.join( [ '-z',
                                   '--export-png=%s' % output,
                                   '--export-area-page',
                               ] )

            else:
                spill = (self.area[3]-self.area[1]) / 20.
                area = "%d:%d:%d:%d" % (self.area[0],
                                        self.area[1],
                                        self.area[2],
                                        self.area[3] + spill)
                settings = ' '.join( [ '-z',
                                       '--export-png=%s' % output,
                                       '--export-area=%s' % area,
                                       '--export-width=%d' % self.options['width'],
                                   ] )

            command = ' '.join( [ str(Settings.inkscape), str(settings), str(self.temp) ] )
            results = Utils.qx(command)
            
            if self.options['page']:
                if self.options['camera']:
                    spill = (self.area[3]-self.area[1]) / 20.
                    axis = self.area[0] - spill
                    if(float(axis) >= 0):
                        axis = '+%f' % axis
                    else:
                        axis = '%f' % axis

                    ordinat = float(svg.root.attrib['height']) - self.area[3] - spill
                    if(float(ordinat) >= 0):
                        ordinat = '+%f' % ordinat
                    else:
                        ordinat = '%f' % ordinat

                    conversion = ' '.join( [ camera_file,
                                             '-geometry %s%s' % (axis, ordinat),
                                             '-composite',
                                             '-background "%s"' % self.options['background'], 
                                             '-flatten',
                                             ] )

#                    output_image = Image(output)
#                    output_image.composite(camera_image, axis, ordinat)

                else:
                    conversion = ' '.join( [ '-background "%s"' % self.options['background'],
                                                 '-flatten',
                                                 ] )
            else:
                conversion = ' '.join( [ '-background "%s"' % self.options['background'],
                                         '-flatten',
                                         '-extent %dx%d+0+0!' % (self.options['width'],
                                                                 self.options['height']),
                                         ] )

            command = ' '.join( [ str(Settings.convert), str(output), str(conversion), str(output),
                                  '&' ] )
            results = Utils.qx(command)
            
            self.printText.emit('  ' + marker + ' ' + output)
            #print '  ' + marker, output
        self.time += 1

    def hold(self, ts=1):
        '''Make a number of duplicates of the most recent frame written.'''
        if ts <= 0: return
        before = "%s/%s%05d.png" % (str(self.options['folder']),
                                    str(self.options['name']),
                                    self.time-1)
        for i in range(ts):
            if not self.isRunning: return
            after = "%s/%s%05d.png" % (str(self.options['folder']),
                                       str(self.options['name']),
                                       self.time)
            if self.options['from'] <= self.time <= self.options['until']:
                shutil.copyfile(before, after)
                self.printText.emit('  = %s' % after)
            self.time += 1

    def pan(self, svg, target, ts=0, margin=1.0):
        '''Shoot the intervening frames from the current camera area toward
        a target camera area.  The camera speed eases into the motion and
        eases to a stop, rather than lurching with a simple linear
        interpolation, but the motion is in a direct path.
        '''
        before = self.area
        if isinstance(target, list):
            pass
        elif target in self.layout:
            target = self.zoom(self.fit(self.locate(target)), margin)
        else:
            return
        if not ts:
            ts = self.speed(before, target,  svg)
        a = V(before)
        b = V(before)
        c = V(target)
        d = V(target)
        for i in range(ts):
            tt = (i + 1) / float(ts)
            where = interpolations.bezier( tt, a, b, c, d ).list()
            self.move(where)
            self.shoot(svg, marker='-')
            
    def cleanup(self):
        '''Remove any temporary files required for rendering.'''
        if os.path.exists(self.temp):
            os.unlink(self.temp)
        
        for f in os.listdir(self.options['folder']):
            if re.search('camera[0-9]*\.png', f):
                os.remove(os.path.join(str(self.options['folder']), f))
