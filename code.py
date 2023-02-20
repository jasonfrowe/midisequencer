#Simple Multi-track Midi Sequencer (email:)jasonfrowe@gmail.com
# GNU Non-commercial Licence -- basically you can use this freely for non-commerical licence.  Any forward IP must carry this licence forward.
from pmk import PMK, number_to_xy, hsv_to_rgb
# from pmk.platform.keybow2040 import Keybow2040 as Hardware          # for Keybow 2040
from pmk.platform.rgbkeypadbase import RGBKeypadBase as Hardware  # for Pico RGB Keypad Base

#import audiocore
#import audiopwmio
import busio
import board
import digitalio
import rotaryio
import array
import time
import supervisor
import math
import random

#for faster math
import ulab.numpy as np

#For display
import terminalio
import displayio
import adafruit_displayio_ssd1306
from adafruit_display_text import label
from adafruit_bitmap_font import bitmap_font

import usb_midi
import adafruit_midi
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.control_change import ControlChange
from adafruit_midi.timing_clock import TimingClock

import adafruit_mcp3xxx.mcp3008 as MCP
from adafruit_mcp3xxx.analog_in import AnalogIn

#Release any displays
displayio.release_displays()

#Variable Potentiometer
spi=busio.SPI(clock=board.GP10, MISO=board.GP12, MOSI=board.GP11)
cs = digitalio.DigitalInOut(board.GP13)
mcp = MCP.MCP3008(spi, cs)

pchannel_thres=0.08 #threshold to determine if Potentiometer has changed (mine is noisy)
pchannel_thres_abs = 129 #Potentiometer output needs to change by at least this amount.
npchannel=5
nptrack=0 #MIDI Channel to send MIDI messages on
#Channel 0 Potentiometer
pchannel=[]
pchannel_value=array.array("H", [0] * npchannel)
pchannel.append(AnalogIn(mcp, MCP.P0))
pchannel.append(AnalogIn(mcp, MCP.P1))
pchannel.append(AnalogIn(mcp, MCP.P2))
#pchannel.append(AnalogIn(mcp, MCP.P3))
pchannel.append(AnalogIn(mcp, MCP.P4))
pchannel.append(AnalogIn(mcp, MCP.P5))
for i in range(npchannel):
    pchannel_value[i] = pchannel[i].value #initialize to current value of potentiometer


#threshold to determine if a key is being held (seconds)
KEY_HOLD_TIME = 1.00

# Set up Keybow
keybow = PMK(Hardware())
keys = keybow.keys

#set key hold time (not currently used) 
for key in keys:
    key.hold_time = KEY_HOLD_TIME
    
#Set up Stop/Start pin
stop_button = board.GP16
stop_pin = digitalio.DigitalInOut(stop_button)
stop_pin.switch_to_input(pull=digitalio.Pull.DOWN)
stop_pin_value=False #if stop button has been pushed
stophold_pin_value=False #if stop button is being held
run_midi=True
    
#Set up track pin
track_button = board.GP22
track_pin = digitalio.DigitalInOut(track_button)
track_pin.switch_to_input(pull=digitalio.Pull.DOWN)
track_pin_value=False

#Set up timing pin
encoder_button = board.GP28
encoder_pin = digitalio.DigitalInOut(encoder_button)
encoder_pin.switch_to_input(pull=digitalio.Pull.DOWN)
encoder_pin_value=False
encoder_style = 0 #0 - global pace ; 1 - single track

#Rotary - for tempo
rot_butA = board.GP26
rot_butB = board.GP27
encoder = rotaryio.IncrementalEncoder(rot_butA, rot_butB)
last_position = None

#Rotary - for note scale
rot_note_butA = board.GP20
rot_note_butB = board.GP21
encoder_rot = rotaryio.IncrementalEncoder(rot_note_butA, rot_note_butB)
last_position_rot = None

#Pad Buttons
npad_total = 16 #number of pad buttons

key_colour_ind = array.array("H", [0] * npad_total) #Tracks colour and note
key_status     = array.array("H", [0] * npad_total) #Tracks status of button pushes

#number of midi channels
ntrack_total = 8 #Total number of tracks

# The MIDI channels for each track in turn: 1, 2, 3, 4
#MIDI_CHANNELS = [1, 2, 3, 4]
midi_ch_num = []
for i in range(ntrack_total):
    midi_ch_num.append(i)
    
# Set the MIDI channels up.
midi_channels=[] #channels for scheduled note to play
midi_channel_sent=[] #the channel the note was actually played on.
midi_ch_min=0
midi_ch_max=15
for channel in midi_ch_num:
    midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=channel)
    midi_channels.append(midi)
    midi_channel_sent.append(midi)

#General unassigned Rotaries
nmidi_spinner=3 #number of free midi spinners
midi_spinner_encoder=[] #encoder hardware
last_midi_spinner_position=[] #last position to check for changes
midi_spinner_channel=[] #midi channel to use 
midi_spinner_value=[] #value to board cast

midi_spinner_encoder.append(rotaryio.IncrementalEncoder(board.GP6, board.GP7))
last_midi_spinner_position.append(None)
midi_spinner_channel.append(npchannel)
midi_spinner_value.append(array.array("H", [0] * ntrack_total))

midi_spinner_encoder.append(rotaryio.IncrementalEncoder(board.GP8, board.GP9))
last_midi_spinner_position.append(None)
midi_spinner_channel.append(npchannel+1)
midi_spinner_value.append(array.array("H", [0] * ntrack_total))

midi_spinner_encoder.append(rotaryio.IncrementalEncoder(board.GP14, board.GP15))
last_midi_spinner_position.append(None)
midi_spinner_channel.append(npchannel+2)
midi_spinner_value.append(array.array("H", [0] * ntrack_total))
    
#Set up  wait states
wait_min=1
wait_max=7
wait_default=4
wait_master_list=[]
wait_list=[]
for i in range(ntrack_total):
    wait_master_list.append(wait_default)
    wait_list.append(wait_default)
#Time between each note
bpm_target = 120
bpm_measured=120
#bpm_meas_idx = -1
#bpm_meas_npt = 50
#bpm_meas = np.array([bpm_target] * bpm_meas_npt)
bpm_min=1
bpm_max=400
#imeunit=1000
#tfunc=supervisor.ticks_ms
timeunit=1000000000 #if ms -> 1000 if ns -> 1000000000
tfunc=time.monotonic_ns
beat_div=16 #ideally this needs to be 24, but the current code cannot update fast enough.
time_interval = 60/(beat_div*bpm_target)*timeunit #0.5 / (2**(wait_max-wait_default+1)) #seconds
time_interval_min = 2.00
tfac = 0.0005 #how much time_interval can change with rotary
max_count = 2**wait_max
dtime = 0.0
ctold =0.0

#track a reference position list
master_pos = array.array("H", [0] * (wait_max+1))

key_colour_ind_list = []
for i in range(ntrack_total):
    key_colour_ind_list.append(array.array("H", [0] * npad_total))

key_play_ind = 0
freqs = array.array("H",[523, 554, 586, 622, 659, 698, 740, 784, 831, 880, 932, 988, 1047]) #Not used
#midi_notes = array.array("H",[72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84])
midi_notes = array.array("H",[60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75]) #This should be tunable
velocity = 127 #default midi velocity

midi_notes_total = 16 #total number of midi notes defined (must match size of midi_notes_list!)
midi_notes_list=[]
midi_notes_inc=12 #increment to increase or decrease scale
#factor to add or remove, so add: (midi_notes_fac * midi_note_inc) to all midi_notes in track
midi_notes_fac = array.array("h", [0] * ntrack_total)
midi_notes_fac_min=-3 #minimum value to avoid midi_notes < 0
midi_notes_fac_max= 3 #maximum value to avoid midi_notes > 128
for i in range(ntrack_total):
    midi_notes_list.append(array.array("H",[60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75]))
midi_notes_chance = array.array("f", [1.0] * ntrack_total) #probability to play a note for each track
midi_notes_mutate = []
for i in range(ntrack_total):
    midi_notes_mutate.append(False)

midi_vel=array.array("H", [127] * ntrack_total)
midi_vel_min=0
midi_vel_max=127

midi_off=array.array("h", [0] * ntrack_total) #if 0 then midi notes stop with next play.  if 1 then notes are sustained 


track = 0 #initialize curent track

# Attach handler functions to all of the keys
for key in keys:
    # A press handler that sends the keycode and turns on the LED
    @keybow.on_press(key)
    def press_handler(key):
        i = key.number
        if key_status[i] == 0:
            key_status[i] == 1
            key_colour_ind_list[track][i]+=1
            if key_colour_ind_list[track][i] > midi_notes_total:
                key_colour_ind_list[track][i]=0
                key.led_off()
            else:
                hue = key_colour_ind_list[track][i]/midi_notes_total
                #print(i,key_status[i],hue)
                # Convert the hue to RGB values.
                r, g, b = hsv_to_rgb(hue, sat, val)
                key.set_led(r, g, b)
    # Catch debounce
    @keybow.on_release(key)
    def release_handler(key):
        i = key.number
        if key_status[i] == 1:
            key_status[i] == 0

play_list=[] #track if a track/note is active
play_end=[]
for i in range(ntrack_total):
    play_list.append(False)
    play_end.append(False)

note_list=[] #initalize notes currently being played
for n in midi_notes:
    note_list.append(n)    


drum_fill=0.25
drum_chance=1.0
drum_style=0
drum_style_old=0
drum_style_min=0
drum_style_max=30 #sets number of styles (should match length of beat_patterns_inX
drum_wait = 6
drum_wait_min = 3
drum_wait_max = 7

#Sets default instruments for Drum generator
beat_inst_list=[]
beat_patterns_in0=[] #Kick
beat_patterns_in1=[] #Snare
beat_patterns_in2=[] #Hat-closed
beat_patterns_in3=[] #Hat-open

#1 Kick
#2 rim shot
#3 snare
#4 hand clap
#5 low conga
#6 mid conga
#7 closed hi
#8 hi conga
#9 low tom
#10 mid tom
#11 open hi
#12 hi tom
#13 maracas
#14 cymbal
#15 cow bell
#16 claves

#0 Blank
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#1 Sgt Pepper
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))

#2 Levee Breaks
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 1,  0, 0, 1, 1,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))

#3 Lady P
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 1, 0,  0, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#4 Pocket Calculator
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))

#5 Funky President
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 1,  0, 0, 0, 1,  0, 1, 1, 0,  0, 0, 0, 1]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 0, 0,  1, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0]))

#6 Amen Brother
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 1, 0,  0, 0, 0, 0,  0, 0, 1, 1,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 1,  0, 1, 0, 0,  1, 0, 0, 1]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#7 Swimming Pools
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 1,  0, 0, 1, 0,  0, 0, 1, 0,  0, 1, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#8 In the air
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))

#9 Afrika
beat_inst_list.append(array.array("H",[1,3,7,4]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 1,  1, 0, 1, 1,  1, 0, 1, 1,  1, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))

#10 Blue Monday
beat_inst_list.append(array.array("H",[1,3,7,4]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))

#11 Confusion
beat_inst_list.append(array.array("H",[1,3,7,4]))
beat_patterns_in0.append(array.array("H",[1, 1, 0, 0,  0, 0, 1, 1,  0, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 1,  1, 0, 1, 1,  1, 0, 1, 1,  1, 0, 1, 1]))
beat_patterns_in3.append(array.array("H",[1, 1, 0, 1,  1, 0, 1, 1,  0, 0, 0, 0,  0, 0, 0, 1]))

#12 Trans Europe Express
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 1, 0, 0,  0, 0, 0, 0,  1, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 1,  1, 0, 0, 1,  1, 0, 1, 1,  1, 0, 0, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#13 Techno 160
beat_inst_list.append(array.array("H",[1,3,14,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0]))

#14 The message
beat_inst_list.append(array.array("H",[1,3,4,11]))
beat_patterns_in0.append(array.array("H",[1, 1, 0, 0,  0, 0, 1, 0,  1, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0]))

#15 Voodoo Ray
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 1, 0,  1, 1, 0, 1,  1, 1, 1, 1,  0, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0,  1, 0, 0, 0]))

#16 In da club
beat_inst_list.append(array.array("H",[1,3,4,11]))
beat_patterns_in0.append(array.array("H",[0, 0, 1, 0,  0, 0, 0, 1,  0, 0, 1, 0,  0, 0, 0, 1]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))

#17 Let the music play
beat_inst_list.append(array.array("H",[1,3,7,4]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))

#18 Sexual healing
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 1,  1, 0, 1, 0,  1, 0, 0, 1]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 1, 1,  0, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 1,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#19 Numbers
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 1,  1, 0, 1, 1,  1, 1, 1, 1,  1, 0, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#20 Revolution 909
beat_inst_list.append(array.array("H",[1,4,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 0, 0,  0, 0, 0, 1,  1, 0, 0, 0,  0, 1, 0, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0]))

#21 Boots n cats
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#22 Hip Hop
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 1, 0,  0, 0, 1, 1,  0, 0, 0, 0,  0, 0, 1, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#23 Standard Break
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 1, 1, 0,  1, 0, 1, 0]))

#24 Unknown drummer
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 1,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 1, 0, 0,  1, 0, 0, 1,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 1, 1, 0,  1, 1, 0, 1,  0, 0, 0, 0,  0, 1, 0, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 1, 0]))

#25 Rock 1
beat_inst_list.append(array.array("H",[1,3,7,14]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 1,  1, 0, 1, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0,  1, 0, 1, 0]))
beat_patterns_in3.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#26 House 1
beat_inst_list.append(array.array("H",[1,3,14,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0]))

#27 House 2
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 1,  0, 1, 0, 0,  0, 0, 1, 0,  0, 1, 0, 0]))

#28 Rumba
beat_inst_list.append(array.array("H",[1,2,14,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 1,  1, 0, 0, 1,  1, 0, 0, 1,  1, 0, 0, 1]))
beat_patterns_in1.append(array.array("H",[1, 0, 0, 1,  0, 0, 0, 1,  0, 0, 1, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))

#29 Techno
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 0, 0,  1, 0, 1, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 1, 0, 0,  0, 0, 0, 0]))
beat_patterns_in3.append(array.array("H",[0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0,  0, 0, 1, 0]))

#30 Synth wave
beat_inst_list.append(array.array("H",[1,3,7,11]))
beat_patterns_in0.append(array.array("H",[1, 0, 0, 0,  0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in1.append(array.array("H",[0, 0, 0, 0,  1, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0]))
beat_patterns_in2.append(array.array("H",[1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1]))
beat_patterns_in3.append(array.array("H",[0, 0, 0, 0,  0, 0, 0, 0,  0, 0, 0, 0,  0, 1, 0, 0]))


cminor_scale=[1,3,4,6,9,11,13,15]
cminor_scale_notes=8
cmajor_scale=[1,3,5,6,8,10,12,13]
cmajor_scale_notes=8
dminor_scale=[3,5,6,8,10,11,13,15]
dminor_scale_notes=8
dmajor_scale=[3,5,7,8,10,12,14,15]
dmajor_scale_notes=8
eminor_scale=[3,5,7,8,10,12,13,15]
eminor_scale_notes=8
emajor_scale=[3,5,7,9,10,12,14,16]
emajor_scale_notes=8
fminor_scale=[4,6,8,9,11,13,14,16]
fminor_scale_notes=8
fmajor_scale=[3,5,6,8,10,11,13,15]
fmajor_scale_notes=8
gminor_scale=[1,3,4,6,8,10,11,13]
gminor_scale_notes=8
gmajor_scale=[1,3,5,7,8,10,12,13]
gmajor_scale_notes=8

#List of scales
nscale = 10
scale_list=[]
scale_name=[]
scale_nnotes=[]

scale_list.append(cminor_scale)
scale_name.append("Cmin")
scale_nnotes.append(8)

scale_list.append(cmajor_scale)
scale_name.append("Cmaj")
scale_nnotes.append(8)

scale_list.append(dminor_scale)
scale_name.append("Dmin")
scale_nnotes.append(8)

scale_list.append(dmajor_scale)
scale_name.append("Dmaj")
scale_nnotes.append(8)

scale_list.append(eminor_scale)
scale_name.append("Emin")
scale_nnotes.append(8)
scale_list.append(emajor_scale)
scale_name.append("Emaj")
scale_nnotes.append(8)

scale_list.append(fminor_scale)
scale_name.append("Fmin")
scale_nnotes.append(8)
scale_list.append(fmajor_scale)
scale_name.append("Fmaj")
scale_nnotes.append(8)

scale_list.append(gminor_scale)
scale_name.append("Gmin")
scale_nnotes.append(8)
scale_list.append(gmajor_scale)
scale_name.append("Gmaj")
scale_nnotes.append(8)


style_names=[]
style_names.append("BPM ")
style_names.append("Wait")
style_names.append("Beat")
style_names.append("Drum")
style_names.append("CMin")

## Display Setup

#release any previously defined pins
#displayio.release_displays()

WIDTH = 128
HEIGHT = 64 

#i2c = busio.I2C (scl=board.GP1, sda=board.GP0)
display_bus = displayio.I2CDisplay(keybow.hardware.i2c(), device_address=0x3d)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=WIDTH, height=HEIGHT)

#Display Colour and Font
color = 0xFFFFFF
font = terminalio.FONT
#font = bitmap_font.load_font("fonts/courR14.bdf")

# Make the display context
splash = displayio.Group()
display.show(splash)

color_bitmap = displayio.Bitmap(WIDTH, HEIGHT, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0x000000  # White

bg_sprite = displayio.TileGrid(color_bitmap, pixel_shader=color_palette, x=0, y=0)
splash.append(bg_sprite)

text_1 = "BPM "+str("%03d" % bpm_target)+" O"+str("%02d" % midi_notes_fac[0])
text_area_1 = label.Label(
    font, text=text_1, color=0xFFFFFF, x=2, y=6
)
splash.append(text_area_1)

text_2 = str(encoder_style)+style_names[encoder_style]+" TR "+str(track+1)
text_area_2 = label.Label(
    font, text=text_2, color=0xFFFFFF, x=2, y=22
)
splash.append(text_area_2)

text_3 = "--- --- ---"
text_area_3 = label.Label(
    font, text=text_3, color=0xFFFFFF, x=2, y=38
)
splash.append(text_area_3)

nmessage=0
nmessage_max=9

md1 = midi_spinner_channel[0]+1
md2 = midi_spinner_channel[1]+1
md3 = midi_spinner_channel[2]+1
text_3 = str("%03d" % md1)+" "+str("%03d" % md2)+" "+str("%03d" % md3)
text_area_3.text = text_3
text_4 = "MC1 MC2 MC3"
text_area_4 = label.Label(
    font, text=text_4, color=0xFFFFFF, x=2, y=54
)
splash.append(text_area_4)

####### end of display set up ##########

#Random fillings
fill_min=0.0
fill_max=1.0
chance_min=0.0
chance_max=1.0

beat_note=1
beat_note_min=1
beat_note_max=16
beat_note_fill=0.75
beat_note_chance=1.0

#scale_min=0
#scale_max=8
#Cmaj_fill=0.75
#Cmaj_chance=1.0
#Cmaj_scale=0
#Cmin_fill=0.75
#Cmin_chance=1.0
#Cmin_scale=0

scale_n=0
scale_fill=0.50
scale_chance=1.0

time_last_note = tfunc() # supervisor.ticks_ms() #initialize clock
key_play_ind = array.array("H", [0] * ntrack_total) #array to hold notes for each track

sat=1.0
val=0.2

icheck=0
icheckmax=100

master_count=0
prev_count_str=bin(max_count+max_count-1)[2:]
count_str=bin(max_count)[2:]
tcorrection = 0.0
while True:
    # Always remember to call keybow.update() on every iteration of your loop!
    
    #Update Time elapsed
    ctime = tfunc()
    #dtime = ctime - ctold
    ctold = ctime
    current_time =  ctime - time_last_note

    #if current_time + dtime/2 >= time_interval:
    if current_time  >= time_interval - tcorrection:
                
        tcorrection = current_time - (time_interval - tcorrection)
        #Update clock time passed
        time_last_note = tfunc()
        #print(tcorrection,current_time,time_interval - tcorrection)
        
        midi_channels[nptrack].send(TimingClock())
        
        keybow.update()

        #Check stop/start pin
        if stop_pin.value and stop_pin_value==False:
            stop_pin_time_last = tfunc()
            stop_pin_value=True
            if run_midi:
                run_midi=False
                for i in range(ntrack_total):
                    note = note_list[i]
                    midi_channels[i].send(NoteOff(note, 0))        
                    play_list[i]=False
                #turn off buttons
                for i in range(npad_total):
                    keys[i].led_off()
                nmessage+=1
                if nmessage>nmessage_max:
                    nmessage=0
                text_area_4.text = str(nmessage)+" Stop     "
                text_area_1.text="           "
                text_area_2.text="           "
                text_area_3.text="           "
                text_area_4.text="           "
            else:
                cold = tfunc()
                time_last_note = cold
                run_midi=True
                #update buttons for current track
                for i in range(npad_total):
                    if key_colour_ind_list[track][i] == 0:
                        keys[i].led_off()
                    else:
                        hue = key_colour_ind_list[track][i]/midi_notes_total
                        r, g, b = hsv_to_rgb(hue, sat, val)
                        keys[i].set_led(r, g, b)
                nmessage+=1
                if nmessage>nmessage_max:
                    nmessage=0
                #text_4 = str(nmessage)+" Start    "
                text_area_1.text = text_1
                text_area_2.text = text_2
                text_area_3.text = text_3
                text_area_4.text = text_4
            #print('Stop/Start button pushed')
        elif stop_pin.value and stop_pin_value==True and stophold_pin_value==False:
            stop_pin_time = tfunc()  - stop_pin_time_last
            if stop_pin_time > KEY_HOLD_TIME*timeunit:
                #print('Reset requested')
                nmessage+=1
                if nmessage>nmessage_max:
                    nmessage=0 
                text_area_4.text = str(nmessage)+" Clear TR"+str(track+1)
                ## TO DO -- Turn off all lights and restore on re-start ##
                for i in range(16):
                    key_colour_ind_list[track][i]=0
                    keys[i].led_off()
                stophold_pin_value=True
        elif stop_pin.value==False and stop_pin_value==True:
            stop_pin_value=False
            stophold_pin_value=False
            #print('Start/Stop button released')
            
        #Work though potentometers and send MIDI messages as needed
        for i in range(npchannel):
            vch = pchannel[i].value
            if abs(vch - pchannel_value[i])/(pchannel_value[i]+1) > pchannel_thres and abs(vch - pchannel_value[i]) > pchannel_thres_abs:
                midicc = int(127*vch/65536)
                #print('midi CC',midicc,i,vch,pchannel_value[i])
                midi_channels[nptrack].send(ControlChange(i,midicc))
                pchannel_value[i]=vch
                
        #Work through MIDI spinner knobs
        for i in range(nmidi_spinner):
            position_midi = midi_spinner_encoder[i].position
            if last_midi_spinner_position[i] is None or position_midi != last_midi_spinner_position[i]:
                if last_midi_spinner_position[i] != None:
                    if encoder_style == 0:
                        msv = midi_spinner_value[i][track] - (position_midi - last_midi_spinner_position[i])
                        midi_spinner_value[i][track] = min(127,max(0,msv))
                        midi_channels[nptrack].send(ControlChange(midi_spinner_channel[i],midi_spinner_value[i][track]))
                        #print(i,midi_spinner_value[i][track])
                    elif encoder_style == 3:
                        if i == 0:
                            drum_fill -= 0.01 * (position_midi - last_midi_spinner_position[i])
                            drum_fill = max(fill_min,min(fill_max,drum_fill))
                        elif i == 1:
                            drum_chance -= 0.01 * (position_midi - last_midi_spinner_position[i])
                            drum_chance = max(chance_min,min(chance_max,drum_chance))
                            midi_notes_chance[0] = drum_chance
                            midi_notes_chance[1] = drum_chance
                            midi_notes_chance[2] = drum_chance
                        elif i == 2:
                            drum_style -= (position_midi - last_midi_spinner_position[i])
                            if  drum_style > drum_style_max:
                                drum_style = drum_style_min
                            elif drum_style < drum_style_min:
                                drum_style = drum_style_max
                        text_1 = "BPM "+str("%03d" % bpm_target)+" O"+str("%02d" % midi_notes_fac[track])
                        text_area_1.text = text_1
                        text_3 = str("%03d" % int(drum_fill*100))+" "+str("%03d" % int(drum_chance*100))+ \
                                 " "+str("%03d" % int(drum_style))
                        text_area_3.text = text_3
                    elif encoder_style == 2:
                        if i == 0:
                            beat_note_fill -= 0.01 * (position_midi - last_midi_spinner_position[i])
                            beat_note_fill = max(fill_min,min(fill_max,beat_note_fill))
                        elif i == 1:
                            beat_note_chance -= 0.01 * (position_midi - last_midi_spinner_position[i])
                            beat_note_chance = max(chance_min,min(chance_max,beat_note_chance))
                            midi_notes_chance[track] = beat_note_chance
                        elif i == 2:
                            beat_note -= (position_midi - last_midi_spinner_position[i])
                            if beat_note < beat_note_min or beat_note > beat_note_max:
                                beat_note = beat_note_min
                        text_3 = str("%03d" % int(beat_note_fill*100))+" "+str("%03d" % int(beat_note_chance*100))+ \
                                 " "+str("%03d" % int(beat_note))
                        text_area_3.text = text_3
                    elif encoder_style == 4:
                        if i == 0:
                            scale_fill -= 0.01 * (position_midi - last_midi_spinner_position[i])
                            scale_fill = max(fill_min,min(fill_max,scale_fill))
                        elif i == 1:
                            scale_chance -= 0.01 * (position_midi - last_midi_spinner_position[i])
                            scale_chance = max(chance_min,min(chance_max,scale_chance))
                            midi_notes_chance[track] = scale_chance
                        elif i == 2:
                            scale_n -= (position_midi - last_midi_spinner_position[i])
                            if scale_n >= nscale:
                                scale_n = 0
                            elif scale_n < 0:
                                scale_n = nscale-1
                            style_names[4]=scale_name[scale_n]
                            text_2 = str(encoder_style)+style_names[encoder_style]+" TR "+str(track+1)
                            text_area_2.text = text_2
                            #if scale_n == 1:
                            #    midi_notes_mutate[track]=True
                        text_3 = str("%03d" % int(scale_fill*100))+" "+str("%03d" % int(scale_chance*100))+ \
                                 " "+str("%03d" % int(scale_n))
                        text_area_3.text = text_3
                    elif encoder_style == 1:
                        if i == 0:
                            midi_ch_num[track] -= (position_midi - last_midi_spinner_position[i])
                            midi_ch_num[track] = min(max(midi_ch_num[track],midi_ch_min),midi_ch_max)
                            midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=midi_ch_num[track])
                            midi_channels[track] = midi
                        if i == 1:
                            midi_vel[track] -= (position_midi - last_midi_spinner_position[i])
                            midi_vel[track] = min(max(midi_vel[track],midi_vel_min),midi_vel_max)
                        if i == 2:
                            midi_off[track] -= (position_midi - last_midi_spinner_position[i])
                            midi_off[track] = min(max(midi_off[track],0),1) #can only be 0 or 1
                                
                        mdisp = midi_ch_num[track]+1
                        text_4 = "M"+str("%02d" % mdisp)+" V"+str("%03d" % midi_vel[track])+" P"+str("%01d" % midi_off[track])
                        text_area_4.text = text_4
                            
                        
            last_midi_spinner_position[i] = position_midi
            
    
        if run_midi:
            
            ##measure actual speed of device
            #bpm_meas_idx+=1
            #if bpm_meas_idx >= bpm_meas_npt:
            #    bpm_measured = np.mean(bpm_meas)
            #    bpm_meas_idx=-1
            #    text_1 = "BPM "+str("%03d" % bpm_target)+" "+str("%03d" % bpm_measured)
            #    text_area_1.text = text_1
            #else:
            #    bpm_meas[bpm_meas_idx] = 60.0/(current_time*8.0)
            
            #Check Encoder pin for tempo/speed
            if encoder_pin.value==False and encoder_pin_value==False:
                encoder_pin_value=True
                if encoder_style<4:
                    encoder_style+=1
                    if encoder_style==3:
                        text_3 = str("%03d" % int(drum_fill*100))+" "+str("%03d" % int(drum_chance*100))+ \
                                 " "+str("%03d" % int(drum_style))
                        text_area_3.text = text_3
                        text_4 = "FIL CHA STY"
                        text_area_4.text = text_4
                    elif encoder_style==2:
                        beat_note_chance = midi_notes_chance[track] #update chance based on current track
                        text_3 = str("%03d" % int(beat_note_fill*100))+" "+str("%03d" % int(beat_note_chance*100))+ \
                                 " "+str("%03d" % int(beat_note))
                        text_area_3.text = text_3
                        text_4 = "FIL CHA NOT"
                        text_area_4.text = text_4
                    elif encoder_style==1:
                        text_3 = "W "+str(wait_list[track])+str(wait_list[1])+str(wait_list[2]) \
                                 +str(wait_list[3])+str(wait_list[4])+str(wait_list[5])+str(wait_list[6]) \
                                 +str(wait_list[7])
                        text_area_3.text = text_3
                        mdisp = midi_ch_num[track]+1
                        text_4 = "M"+str("%02d" % mdisp)+" V"+str("%03d" % midi_vel[track])+" P"+str("%01d" % midi_off[track])
                        text_area_4.text = text_4
                    elif encoder_style==4:
                        scale_chance= midi_notes_chance[track] #update chance based on current track
                        style_names[4]=scale_name[scale_n]
                        text_3 = str("%03d" % int(scale_fill*100))+" "+str("%03d" % int(scale_chance*100))+ \
                                 " "+str("%03d" % int(scale_n))
                        text_area_3.text = text_3
                        text_4 = "FIL CHA SCA"
                        text_area_4.text = text_4
                else:
                    encoder_style=0
                    md1 = midi_spinner_channel[0]+1
                    md2 = midi_spinner_channel[1]+1
                    md3 = midi_spinner_channel[2]+1
                    text_3 = str("%03d" % md1)+" "+str("%03d" % md2)+" "+str("%03d" % md3)
                    text_area_3.text = text_3
                    text_4 = "MC1 MC2 MC3"
                    text_area_4.text = text_4
                #print('Encoder button pushed')
                #print('Encoder style = ',encoder_style)
                text_2 = str(encoder_style)+style_names[encoder_style]+" TR "+str(track+1)
                text_area_2.text = text_2
            elif encoder_pin.value==True and encoder_pin_value==True:
                encoder_pin_value=False
                #print('Encoder button released')
                
            position = encoder.position #get update from encoder
            if last_position is None or position != last_position: #If encoder changed, process change
                if encoder_style==0: #in Mode-0 we change global timing interval between notes
                    #if last_position != None:
                    #    time_interval += tfac * (position - last_position)
                    #if time_interval < time_interval_min:
                    #    time_interval = time_interval_min
                    if last_position != None:
                        bpm_target += (position - last_position)
                        bpm_target = max(min(bpm_target,bpm_max),bpm_min)
                        time_interval = 60.0/(beat_div*bpm_target)*timeunit
                        #print('BPM target: ',bpm_target,time_interval)
                        text_1 = "BPM "+str("%03d" % bpm_target)+" O"+str("%02d" % midi_notes_fac[track])
                        text_area_1.text = text_1
                elif encoder_style==1: #In Mode-1 we adjust timing interval for a single track
                    if last_position != None:
                        wait_list[track] += (position - last_position)
                        wait_list[track] = min(wait_max,max(wait_min,wait_list[track]))
                        #print(wait_list)
                        #nmessage+=1
                        #if nmessage>nmessage_max:
                        #    nmessage=0
                        text_3 = "W "+str(wait_list[0])+str(wait_list[1])+str(wait_list[2]) \
                                 +str(wait_list[3])+str(wait_list[4])+str(wait_list[5])+str(wait_list[6]) \
                                 +str(wait_list[7])
                        text_area_3.text = text_3
                elif encoder_style==2:
                    if last_position != None:
                        wait_list[track]=random.randint(3,6)
                        for i in range(16):
                            rnum = random.random()
                            if rnum <= beat_note_fill:
                                key_colour_ind_list[track][i]=beat_note
                                hue = key_colour_ind_list[track][i]/midi_notes_total
                                r, g, b = hsv_to_rgb(hue, sat, val)
                                keys[i].set_led(r, g, b)
                            else:
                                key_colour_ind_list[track][i]=0
                                keys[i].led_off()
                        #print('Random one-beat applied')
                        #nmessage+=1
                        #if nmessage>nmessage_max:
                        #    nmessage=0
                        #text_4 = str(nmessage)+" RND Beat "
                        #text_area_4.text = text_4
                elif encoder_style==3:
                    if last_position != None:
                        if drum_style == 0:
                            midi_vel[3] = 90 #reduce sound on open-hat
                            for j in range(4):
                                inst=beat_inst_list[drum_style][j] #random.randint(1,16)
                                track1=j
                                midi_off[track1] = 1 #sustain drum sounds
                                wait_list[track1]=random.randint(5,6) #3+j 
                                midi_notes_fac[track1] = -2 #update octave for drum notes
                                midi_ch_num[track1] = 0 #use first midi track for all drum channels
                                midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=midi_ch_num[track1])
                                midi_channels[track1] = midi
                                for i in range(midi_notes_total):
                                    midi_notes_list[track1][i] = midi_notes[i] + midi_notes_fac[track1]*midi_notes_inc
                                for i in range(16):
                                    rnum = random.random()
                                    if rnum <= drum_fill:
                                        key_colour_ind_list[track1][i]=inst
                                        if track==track1:
                                            hue = key_colour_ind_list[track1][i]/midi_notes_total
                                            r, g, b = hsv_to_rgb(hue, sat, val)
                                            keys[i].set_led(r, g, b)
                                    else:
                                        key_colour_ind_list[track1][i]=0
                                        if track==track1:
                                            keys[i].led_off()
                        elif drum_style > 0:
                            #wait1 = random.randint(5,6)
                            if drum_style == drum_style_old:
                                drum_wait+=1
                                if drum_wait > drum_wait_max:
                                    drum_wait = drum_wait_min
                            wait1 = drum_wait
                            drum_style_old = drum_style
                            midi_vel[3] = 90 #reduce sound on open-hat
                            for j in range(4):
                                midi_off[j] = 1 #sustain drum sounds
                                inst=beat_inst_list[drum_style][j] #random.randint(1,16)
                                track1=j
                                wait_list[track1]=wait1
                                midi_notes_fac[track1] = -2 #update octave for drum notes
                                midi_ch_num[track1] = 0 #use first midi track for all drum channels
                                midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=midi_ch_num[track1])
                                midi_channels[track1] = midi
                                for i in range(midi_notes_total):
                                    midi_notes_list[track1][i] = midi_notes[i] + midi_notes_fac[track1]*midi_notes_inc
                                for i in range(16):
                                    if j==0:
                                        rnum = beat_patterns_in0[drum_style][i]
                                    elif j==1:
                                        rnum = beat_patterns_in1[drum_style][i]
                                    elif j==2:
                                        rnum = beat_patterns_in2[drum_style][i]
                                    elif j==3:
                                        rnum = beat_patterns_in3[drum_style][i]
                                    if rnum > 0:
                                        key_colour_ind_list[track1][i]=inst
                                        if track==track1:
                                            hue = key_colour_ind_list[track1][i]/midi_notes_total
                                            r, g, b = hsv_to_rgb(hue, sat, val)
                                            keys[i].set_led(r, g, b)
                                    else:
                                        key_colour_ind_list[track1][i]=0
                                        if track==track1:
                                            keys[i].led_off()
                                
                        #nmessage+=1
                        #if nmessage>nmessage_max:
                        #    nmessage=0
                        #text_4 = str(nmessage)+" RND Drum "
                        #text_area_4.text = text_4
                elif encoder_style==4:
                    if last_position != None:
                        #wait_list[track]=random.randint(2,6)
                        for i in range(16):
                            rnum = random.random()
                            if rnum <= scale_fill:
                                rnote=random.randint(0,scale_nnotes[scale_n]-1)
                                key_colour_ind_list[track][i]=scale_list[scale_n][rnote]
                                hue = key_colour_ind_list[track][i]/midi_notes_total
                                r, g, b = hsv_to_rgb(hue, sat, val)
                                keys[i].set_led(r, g, b)
                            else:
                                key_colour_ind_list[track][i]=0
                                keys[i].led_off()
                        #print('Random notes from scale applied')
                        
            last_position = position
            
            #Check Encoder pin for midi-scale
            position_rot = encoder_rot.position
            if last_position_rot is None or position_rot != last_position_rot:
                if last_position_rot != None:
                    #print('midi-scale!')
                    midi_notes_fac[track] += (position_rot - last_position_rot)
                    midi_notes_fac[track] = max(midi_notes_fac[track], midi_notes_fac_min)
                    midi_notes_fac[track] = min(midi_notes_fac[track], midi_notes_fac_max)
                    #print(track,midi_notes_fac[track])
                    for i in range(midi_notes_total):
                        midi_notes_list[track][i] = midi_notes[i] + midi_notes_fac[track]*midi_notes_inc
                    text_1 = "BPM "+str("%03d" % bpm_target)+" O"+str("%02d" % midi_notes_fac[track])
                    text_area_1.text = text_1
            last_position_rot = position_rot
        
            #Check track pin
            if track_pin.value and track_pin_value==False:
                #print('Button pressed')
                track_pin_value=True #If button is pressed we ignore all events until key is released
                track+=1 #move to next track
                if track >= ntrack_total:
                    track=0
                text_1 = "BPM "+str("%03d" % bpm_target)+" O"+str("%02d" % midi_notes_fac[track])
                text_area_1.text = text_1
                #text_2 = "EN "+str(encoder_style)+" TR "+str(track+1)+" "
                text_2 = str(encoder_style)+style_names[encoder_style]+" TR "+str(track+1)
                text_area_2.text = text_2
                if encoder_style==4:
                    scale_chance = midi_notes_chance[track]
                    text_3 = str("%03d" % int(scale_fill*100))+" "+str("%03d" % int(scale_chance*100))+ \
                             " "+str("%03d" % int(scale_n))
                    text_area_3.text = text_3
                elif encoder_style==1:
                    mdisp = midi_ch_num[track]+1
                    text_4 = "M"+str("%02d" % mdisp)+" V"+str("%03d" % midi_vel[track])+" P"+str("%01d" % midi_off[track])
                    text_area_4.text = text_4
                #update buttons for current track
                for i in range(npad_total):
                    if key_colour_ind_list[track][i] == 0:
                        keys[i].led_off()
                    else:
                        hue = key_colour_ind_list[track][i]/midi_notes_total
                        r, g, b = hsv_to_rgb(hue, sat, val)
                        keys[i].set_led(r, g, b)
                #print('track ',track)
            elif track_pin.value==False and track_pin_value==True:
                #print('Button released')
                track_pin_value=False #Button has been released so we monitor for next event.
            
            #Update binary master count clock
            prev_count_str=bin(max_count+master_count)[2:]
            master_count+=1
            if master_count >= max_count:
                master_count=0
            
            count_str=bin(max_count+master_count)[2:]
            #print(master_count,count_str)
        
            #make current key being played white
            if count_str[wait_list[track]]=='0':
                keys[key_play_ind[track]].set_led(255, 255, 255)
        
            #Loop though the tracks and play or turn off notes
            for i in range(ntrack_total):
                #play = play_list[i]
                
                if play_end[i] and count_str[wait_list[i]]=='0':
                    note = note_list[i]
                    if midi_off[i] == 0: #flag for sustaining notes
                        midi_channel_sent[i].send(NoteOff(note, 0))
                    play_end[i]=False
                
                #if key is not busy, then play a note
                if play_list[i]==False and key_colour_ind_list[i][key_play_ind[i]]>0 and count_str[wait_list[i]]=='0':
                    #roll dice to play note
                    rnum = random.random()
                    if rnum <= midi_notes_chance[i]:
                        velocity=midi_vel[i]
                    else:
                        velocity=0
                        #if midi_notes_mutate[i]==True:
                        #    rnote=random.randint(0,cminor_scale_notes-1)
                        #    key_colour_ind_list[i][key_play_ind[i]]=cminor_scale[rnote]
                        #    if i == track:
                        #        hue = key_colour_ind_list[i][key_play_ind[i]]/midi_notes_total
                        #        r, g, b = hsv_to_rgb(hue, sat, val)
                        #        keys[key_play_ind[i]].set_led(r, g, b)
                    play_list[i]=True
                    note = midi_notes_list[i][key_colour_ind_list[i][key_play_ind[i]]-1]
                    midi_channels[i].send(NoteOn(note, velocity))
                    note_list[i] = note
                    midi_channel_sent[i] = midi_channels[i]
        
                #if time has elapsed, turn off the note.
                if play_list[i]==True and count_str[wait_list[i]]=='1':
                    play_end[i]=True
                    play_list[i]=False
                    #note = note_list[i]
                    #midi_channels[i].send(NoteOff(note, 0))
                    #play_list[i]=False
                    
            #restore previous key to correct colour
            prev_key = key_play_ind[track] - 1
            if prev_key < 0:
                prev_key += npad_total
            if key_colour_ind_list[track][prev_key] == 0:
                keys[prev_key].led_off()
            else:
                hue = key_colour_ind_list[track][prev_key]/midi_notes_total
                r, g, b = hsv_to_rgb(hue, sat, val)
                keys[prev_key].set_led(r, g, b)
            
            #Update active key for each track based on timer 
            #for i in range(ntrack_total):
            #    if count_str[wait_list[i]]=='1' and prev_count_str[wait_list[i]]=='0':
            #        key_play_ind[i]+=1
            #        if key_play_ind[i] > npad_total-1:
            #            key_play_ind[i]=0
                        
            #Update active key for each track based on timer -- keep tracks in sync
            for i in range(wait_min,wait_max+1):
                if count_str[i]=='1' and prev_count_str[i]=='0':
                    master_pos[i]+=1
                    if master_pos[i] > npad_total-1:
                        master_pos[i]=0
            for i in range(ntrack_total):
                key_play_ind[i] = master_pos[wait_list[i]]
            
                    

