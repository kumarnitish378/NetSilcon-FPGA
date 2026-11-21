@echo off
REM Simulate NetSilcon-6x4 against the Python golden vectors (both modes) and the board self-test.
cd /d %~dp0..
if not exist sim mkdir sim
copy /y gen\*.mem sim\ >nul
cd sim
for %%P in (1 2) do (
  echo ===== PHASES=%%P
  iverilog -g2005 -I ..\gen -P tb_netsilcon.PHASES=%%P -o n%%P.vvp ..\tb\tb_netsilcon.v ..\rtl\netsilcon_top.v ..\rtl\nn_layer.v
  vvp -n n%%P.vvp
)
echo ===== Board self-test (Tang Nano 20K top)
iverilog -g2005 -I ..\gen -o board.vvp ..\tb\tb_board.v ..\board\tangnano20k_selftest.v ..\rtl\netsilcon_top.v ..\rtl\nn_layer.v
vvp -n board.vvp
cd ..
