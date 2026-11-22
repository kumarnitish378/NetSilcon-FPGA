// Optional: records waveforms of tb_netsilcon into sim/netsilcon.vcd for GTKWave.
// Compiled alongside the normal testbench (see scripts/run_waves.sh).
module dump_waves;
    initial begin
        $dumpfile("netsilcon.vcd");
        $dumpvars(3, tb_netsilcon);   // testbench + top + layers (3 levels deep)
    end
endmodule
