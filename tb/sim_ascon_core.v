// Simulation wrapper for tb_ascon_core: supplies the clock, waits for the
// testbench to finish and prints the verdict. Simulator-only code.
//
//   iverilog -g2005 -o build/tb_ascon_core.vvp \
//       rtl/ascon_sbox.v rtl/ascon_round.v rtl/ascon_core.v \
//       tb/tb_ascon_core.v tb/sim_ascon_core.v
//   vvp build/tb_ascon_core.vvp            (add +vcd to dump waveforms)
`timescale 1ns / 1ps
module sim_ascon_core;
    reg  clk = 1'b0;
    wire finished, failed;

    tb_ascon_core tb (.clk(clk), .finished(finished), .failed(failed));

    always #5 clk = ~clk;

    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("build/tb_ascon_core.vcd");
            $dumpvars(0, sim_ascon_core);
        end
    end

    // Report each result as the core produces it.
    always @(posedge clk) begin
        if (tb.done)
            $display("t=%0d  vector %0d  x0=%h x1=%h x2=%h x3=%h x4=%h  %s",
                     tb.t, tb.vec, tb.x0, tb.x1, tb.x2, tb.x3, tb.x4,
                     tb.state_ok ? "ok" : "MISMATCH");
        if (finished) begin
            if (failed) $display("RESULT: FAILED");
            else        $display("RESULT: all checks passed");
            $finish;
        end
    end

    initial begin
        #100000;
        $display("RESULT: FAILED (timeout)");
        $finish;
    end
endmodule
