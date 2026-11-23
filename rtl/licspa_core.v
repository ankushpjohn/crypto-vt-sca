// Ascon core with the LiCSPA countermeasure on the state register
// (Lightweight Countermeasures Against Static Power Side-Channel Attacks,
// ISCAS 2025, arXiv 2402.03196), reimplemented for this project.
//
// Identical to rtl/ascon_core.v except for the 320 state flip-flops. Each
// state bit i whose bit is set in `LICSPA_MASK` is a two-path primitive:
//
//              +--[ FF a ]--+
//   next[i] ---|            |--- mux ---> q[i]
//              +--[ FF b ]--+    ^
//   ctl[i] --- selects the path that captures, and the mux input
//
// When ctl[i] = 0, FF a captures and FF b holds (its D is fed back from its own
// output: the paper's feedback loop); when ctl[i] = 1 the roles swap. The idle
// FF keeps whatever it held from an earlier run, so its leakage is unrelated
// to the current data. The flow (eval/licspa_sweep.py) puts both FFs of every
// primitive in LVT, as the paper does, and can also randomise their drive
// strength (DFFHQNx1/x2/x3).
//
// Interpretation of CTL. The paper drives CTL from a random number generator
// and requires the outputs of both paths to be "functionally equivalent". We
// take ctl as a random value per run, held constant from `start` to `done`
// (driven by an RNG outside the core), so the output mux can use it directly
// and the cipher result is unchanged. A per-cycle CTL would need one extra
// flip-flop per primitive to remember which path holds the current value.
//
// Bit numbering of the 320-bit state: bit 64*w + j is bit j of word x<w>.
// The mask comes from licspa_cfg.vh, written by the sweep script; the source
// lines of the two primitive FFs and the plain FF are distinct so that the
// flow can find the primitive FFs in the netlist from their src attribute.
`include "licspa_cfg.vh"

module licspa_core (
    input  wire         clk,
    input  wire         rst,
    input  wire         start,
    input  wire [63:0]  key0,
    input  wire [63:0]  key1,
    input  wire [63:0]  nonce0,
    input  wire [63:0]  nonce1,
    input  wire [319:0] ctl,
    output wire         busy,
    output reg          done,
    output wire [63:0]  x0,
    output wire [63:0]  x1,
    output wire [63:0]  x2,
    output wire [63:0]  x3,
    output wire [63:0]  x4
);
    localparam [63:0]  IV   = 64'h0000_1000_808c_0001;
    localparam [319:0] MASK = `LICSPA_MASK;

    reg       running;
    reg [3:0] round;
    wire [7:0] rc = {~round, round};

    wire [63:0] y0, y1, y2, y3, y4;
    ascon_round u_round (
        .x0(x0), .x1(x1), .x2(x2), .x3(x3), .x4(x4), .rc(rc),
        .y0(y0), .y1(y1), .y2(y2), .y3(y3), .y4(y4)
    );

    wire last = (round == 4'd11);

    always @(posedge clk) begin
        if (rst) begin
            running <= 1'b0;
            done    <= 1'b0;
        end else begin
            done <= running & last & ~start;
            if (start)
                running <= 1'b1;
            else if (last)
                running <= 1'b0;
        end
    end

    always @(posedge clk) begin
        if (start)
            round <= 4'd0;
        else if (running)
            round <= round + 4'd1;
    end

    // Next state of all 320 bits: load on start, otherwise one round.
    wire [319:0] nxt = start ? {nonce1, nonce0, key1, key0, IV}
                             : {y4, y3, y2, y1, y0};
    wire [319:0] q;

    genvar i;
    generate
        for (i = 0; i < 320; i = i + 1) begin : bitreg
            if (MASK[i]) begin : prim
                reg a, b;
                always @(posedge clk) if (!ctl[i]) a <= nxt[i];   // LICSPA_FF_A
                always @(posedge clk) if (ctl[i])  b <= nxt[i];   // LICSPA_FF_B
                assign q[i] = ctl[i] ? b : a;
            end else begin : plain
                reg r;
                always @(posedge clk) r <= nxt[i];               // PLAIN_FF
                assign q[i] = r;
            end
        end
    endgenerate

    assign {x4, x3, x2, x1, x0} = q;
    assign busy = running;
endmodule
