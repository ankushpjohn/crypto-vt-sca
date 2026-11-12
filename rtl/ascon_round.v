// One round of the Ascon permutation (NIST SP 800-232), purely combinational.
//
//   1. constant addition : the 8-bit round constant is XORed into the low
//                          byte of x2
//   2. substitution      : 64 S-box columns; column j takes bit j of x0..x4
//   3. linear diffusion  : each word is XORed with two rotations of itself
//
// The state is five 64-bit words x0..x4 (S0..S4 in the standard). Bit 0 is
// the least significant bit of a word.
module ascon_round (
    input  wire [63:0] x0,
    input  wire [63:0] x1,
    input  wire [63:0] x2,
    input  wire [63:0] x3,
    input  wire [63:0] x4,
    input  wire [7:0]  rc,
    output wire [63:0] y0,
    output wire [63:0] y1,
    output wire [63:0] y2,
    output wire [63:0] y3,
    output wire [63:0] y4
);
    // 1. Constant addition.
    wire [63:0] c2 = x2 ^ {56'd0, rc};

    // 2. Substitution layer.
    wire [63:0] s0, s1, s2, s3, s4;
    ascon_sbox #(.W(64)) u_sbox (
        .x0(x0), .x1(x1), .x2(c2), .x3(x3), .x4(x4),
        .y0(s0), .y1(s1), .y2(s2), .y3(s3), .y4(s4)
    );

    // 3. Linear diffusion layer. {s[n-1:0], s[63:n]} is s rotated right by n.
    assign y0 = s0 ^ {s0[18:0], s0[63:19]} ^ {s0[27:0], s0[63:28]};
    assign y1 = s1 ^ {s1[60:0], s1[63:61]} ^ {s1[38:0], s1[63:39]};
    assign y2 = s2 ^ {s2[0],    s2[63:1]}  ^ {s2[5:0],  s2[63:6]};
    assign y3 = s3 ^ {s3[9:0],  s3[63:10]} ^ {s3[16:0], s3[63:17]};
    assign y4 = s4 ^ {s4[6:0],  s4[63:7]}  ^ {s4[40:0], s4[63:41]};
endmodule
