// Round-per-cycle Ascon-AEAD128 initialisation core (NIST SP 800-232).
//
// On `start` the state register is loaded with the initial state
//     x0 = IV,  x1 = key0,  x2 = key1,  x3 = nonce0,  x4 = nonce1
// and the core then applies one permutation round per clock cycle. `done` is
// high for exactly one cycle, thirteen cycles after `start`, when x0..x4 hold
// the state after twelve rounds.
//
// The state register is free-running: it has no hold enable and keeps applying
// rounds after `done`, so x0..x4 must be sampled in the `done` cycle. This is
// deliberate. A hold enable would be one flip-flop driving all 320 state bits,
// and without buffer insertion (which this flow does not have) that single
// net, not the round logic, would set the clock period.
//
// key0/key1 and nonce0/nonce1 are the 64-bit state words S1..S4 of the
// standard. Converting the 16-byte key and nonce to these words (the standard
// loads bytes little-endian) is left to the testbench or software model, so
// that no byte-order convention is buried in the hardware.
//
// Side-channel view: in the cycle after `start`, the state register holds
// IV | key | nonce and the round logic computes round 1. Stopping the clock
// there is the primary static-power attack point. Column j of the S-box layer
// then sees one IV bit, key0[j], key1[j], nonce0[j] and nonce1[j].
//
// The state register has no reset: it is always loaded before use. Only the
// control flip-flops are reset (synchronous, active high).
module ascon_core (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,
    input  wire [63:0] key0,
    input  wire [63:0] key1,
    input  wire [63:0] nonce0,
    input  wire [63:0] nonce1,
    output wire        busy,
    output reg         done,
    output reg  [63:0] x0,
    output reg  [63:0] x1,
    output reg  [63:0] x2,
    output reg  [63:0] x3,
    output reg  [63:0] x4
);
    // Initial value for Ascon-AEAD128.
    localparam [63:0] IV = 64'h0000_1000_808c_0001;

    reg       running;
    reg [3:0] round;   // 0 .. 11

    // Round constant for round r of the 12-round permutation:
    // high nibble 15 - r, low nibble r  (0xf0, 0xe1, ... 0x4b).
    wire [7:0] rc = {~round, round};

    wire [63:0] y0, y1, y2, y3, y4;
    ascon_round u_round (
        .x0(x0), .x1(x1), .x2(x2), .x3(x3), .x4(x4), .rc(rc),
        .y0(y0), .y1(y1), .y2(y2), .y3(y3), .y4(y4)
    );

    wire last = (round == 4'd11);

    // Control.
    always @(posedge clk) begin
        if (rst) begin
            running <= 1'b0;
            done    <= 1'b0;
        end else begin
            done <= running & last;
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

    // State register: load on start, otherwise one round per cycle.
    always @(posedge clk) begin
        if (start) begin
            x0 <= IV;
            x1 <= key0;
            x2 <= key1;
            x3 <= nonce0;
            x4 <= nonce1;
        end else begin
            x0 <= y0;
            x1 <= y1;
            x2 <= y2;
            x3 <= y3;
            x4 <= y4;
        end
    end

    assign busy = running;
endmodule
