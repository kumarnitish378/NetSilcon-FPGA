# Media

| File | Length | What it shows |
|---|---|---|
| [`NetSilcon_Demo.mp4`](NetSilcon_Demo.mp4) | 2:07 | Demo of NetSilcon-6x4 on the Sipeed Tang Nano 20K: a neural network built directly in FPGA hardware, with loadable models |
| [`NetSilcon_Keynote.mp4`](NetSilcon_Keynote.mp4) | 2:05 | Keynote-style introduction to the NetSilcon idea |
| [`youtube/NetSilcon_YouTube.mp4`](youtube/NetSilcon_YouTube.mp4) | 8:49 | Full YouTube explainer, English voice-over (Kokoro af_heart), captions burnt in |

Datasheet (preliminary target specification): [`NetSilcon-6x4_Datasheet.pdf`](../NetSilcon-Models/NetSilcon-6x4/docs/NetSilcon-6x4_Datasheet.pdf).

## YouTube explainer (youtube/)

| File | What it is |
|---|---|
| [`youtube/NetSilcon_YouTube.mp4`](youtube/NetSilcon_YouTube.mp4) | 1920 × 1080, 30 fps, 8:49 |
| [`youtube/NetSilcon_YouTube_thumbnail.jpg`](youtube/NetSilcon_YouTube_thumbnail.jpg) | 1280 × 720 thumbnail (real board photo) |
| [`youtube/NetSilcon_YouTube.en.srt`](youtube/NetSilcon_YouTube.en.srt) | English captions |
| [`youtube/YouTube_upload_kit.md`](youtube/YouTube_upload_kit.md) | Titles, description with chapters, tags, pinned comment, upload plan |
| [`youtube/source/`](youtube/source/) | Narration script, slides (HTML) and build scripts used to render the video |

## Board photos (photos/)

Real photos of our Sipeed Tang Nano 20K (Gowin GW2AR-18), 2576 × 1450 JPEG: running with LEDs lit
(`board_angle_leds`, `board_usb_leds`), close-ups of the FPGA and the BL616 USB bridge (`board_top_leds`,
`board_closeup_chips`), and the bare board top and bottom (`board_top_new`, `board_bottom_pins`).

## Launch images (social/)

1200 × 1200 PNG, one idea each, every number from the logs. Source: `social/cards_source.html`
(rendered with a headless browser; fonts from the website).

| File | Message |
|---|---|
| [`social/01_cycles_31x.png`](social/01_cycles_31x.png) | 448 vs ≈ 14,100 clock cycles per inference (NetSilcon-64x6 vs laptop CPU) |
| [`social/02_fix_shape_new_job.png`](social/02_fix_shape_new_job.png) | One bitstream, three model files, three jobs (NetSilcon-6x4) |
| [`social/03_fpga_drove_rover.png`](social/03_fpga_drove_rover.png) | Hardware-in-the-loop: 19,200 decisions, 0 mismatches, 0 crashes |
| [`social/04_two_engines.png`](social/04_two_engines.png) | NetSilcon-6x4 and NetSilcon-64x6 side by side |

## Launch kit (launch/)

Everything for the NetSilcon-64x6 launch in one folder: the four images, the LinkedIn post and first comment,
the X thread, the LinkedIn article, the Reddit posts and both datasheets. See [`launch/README.md`](launch/README.md).
