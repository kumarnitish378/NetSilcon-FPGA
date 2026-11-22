// =============================================================================
// NetSilcon-64x6 LINK DIAGNOSIS top: the complete 64x6 board top (UART, parser,
// replies, D1/D2 commands, loader) WITHOUT the engine and the 32 weight RAMs.
// An inference (A5 x0..x15) answers 5A x0..x15 argmax latency after 448 clocks
// (y = x, so the host can check it). Purpose: find out whether the UART reply
// damage seen on the board comes from the engine/RAM part of the chip.
// In Gowin: same project, set Top Module to tangnano20k_ns64_linkonly.
// =============================================================================
module tangnano20k_ns64_linkonly (
    input  wire       clk,
    input  wire       uart_rx,
    output wire       uart_tx,
    output wire [5:0] leds
);
    tangnano20k_ns64 #(.WITH_ENGINE(0)) u (.clk(clk), .uart_rx(uart_rx), .uart_tx(uart_tx), .leds(leds));
endmodule
