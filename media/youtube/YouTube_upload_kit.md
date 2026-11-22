# NetSilcon YouTube upload kit

## Title (pick one; first is recommended, 60 chars)
1. Neural Network on FPGA: Built Into the Hardware, Not a CPU
2. I Put a Neural Network Inside an FPGA (31x Fewer Clock Cycles)
3. Neural Network on FPGA Explained: Tang Nano 20K + Verilog

## Description (paste as is)
A neural network built directly into FPGA logic, not running on a processor. NetSilcon is an open-source engine on the Sipeed Tang Nano 20K (Gowin GW2AR-18): the network shape is fixed in Verilog, the weights are loaded over USB. Fix the shape. Load the numbers. New job.

In this video, step by step and with real measured numbers:
- what a neural network actually computes (only multiply and add)
- why an FPGA can run 64 neurons in the same clock tick
- NetSilcon-6x4: 170 parameters, 15 clock cycles, three jobs on one board
- NetSilcon-64x6: 22,928 parameters, 448 clock cycles, 31x fewer cycles than a laptop CPU
- the honest part: at 27 MHz the laptop still finishes first
- hardware in the loop: 19,200 robot decisions, 0 mismatches, 0 crashes

Chapters
0:00 Intro
0:27 The problem
1:04 What is a neural network?
1:44 CPU vs FPGA
2:07 The NetSilcon idea
2:49 NetSilcon-6x4
3:36 NetSilcon-64x6
3:57 Inside NetSilcon-64x6
4:50 Safe model updates
5:19 The numbers
5:36 The honest part
6:05 Driving a robot
6:36 Hardware in the loop
7:03 How I know it's right
7:28 A lesson
7:47 Where it fits
8:12 Open source

Links
Website: https://kumarnitish378.github.io/NetSilcon/
Source code (Verilog, Python, models, logs): https://github.com/kumarnitish378/NetSilcon-FPGA
Rover simulator in your browser: https://kumarnitish378.github.io/NetSilcon/playground/
NetSilcon-64x6 datasheet: https://kumarnitish378.github.io/NetSilcon/files/NetSilcon-64x6_Datasheet.pdf
LinkedIn (suggest a use case): https://www.linkedin.com/in/nitish-kumar-sharma-21801013b/

What decision would you give it? Up to 16 sensor readings in. Tell me in the comments; the best idea becomes the next trained model.

All numbers in this video come from logs in the repository. The 500 MHz chip figure is an assumption, not a measurement. The robot runs in simulation with the real FPGA making every decision; the safety stop and supervisor still run on the PC.

#FPGA #NeuralNetwork #Verilog

## Tags (YouTube tag box, comma separated)
neural network on fpga, fpga neural network, fpga ai accelerator, tang nano 20k, gowin fpga, verilog neural network, tinyml fpga, edge ai, fpga tutorial, neural network hardware, ai chip, hardware accelerator, int8 quantization, fpga vs cpu, hardware in the loop, netsilcon, sipeed tang nano, embedded ai, neural network explained, fpga project

## Pinned comment
Thanks for watching. Everything is open source: https://github.com/kumarnitish378/NetSilcon-FPGA
Question for you: what decision would you give a tiny on-chip neural network? Up to 16 sensor readings in (motor current, vibration, battery cells, distance sensors...). The best idea becomes the next trained model.

## Upload settings
- Thumbnail: NetSilcon_YouTube_thumbnail.jpg (1280x720)
- Captions: upload NetSilcon_YouTube.en.srt as English (the captions are also burnt in, so set it but it is optional)
- Category: Science & Technology; language: English; not made for kids
- End screen (last 20 s, from 8:29): subscribe button + "best for viewer" video; add a link card to the website if your channel is eligible
- Cards: at 3:21 (rover simulator) link the playground; at 6:36 (HIL) link the GitHub results
- Playlist: create "NetSilcon: Neural Network on FPGA" and add the Demo and Keynote videos too
- First 24 h: share the video in the LinkedIn post and the Reddit posts from media/launch, reply to every comment
