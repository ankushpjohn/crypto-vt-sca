// Reference Ascon S-box as the lookup table printed in NIST SP 800-232.
// Used only to check rtl/ascon_sbox.v; never synthesised into a design.
module ascon_sbox_ref (
    input  wire [4:0] x,
    output reg  [4:0] y
);
    always @* begin
        case (x)
            5'h00: y = 5'h04;  5'h01: y = 5'h0b;  5'h02: y = 5'h1f;  5'h03: y = 5'h14;
            5'h04: y = 5'h1a;  5'h05: y = 5'h15;  5'h06: y = 5'h09;  5'h07: y = 5'h02;
            5'h08: y = 5'h1b;  5'h09: y = 5'h05;  5'h0a: y = 5'h08;  5'h0b: y = 5'h12;
            5'h0c: y = 5'h1d;  5'h0d: y = 5'h03;  5'h0e: y = 5'h06;  5'h0f: y = 5'h1c;
            5'h10: y = 5'h1e;  5'h11: y = 5'h13;  5'h12: y = 5'h07;  5'h13: y = 5'h0e;
            5'h14: y = 5'h00;  5'h15: y = 5'h0d;  5'h16: y = 5'h11;  5'h17: y = 5'h18;
            5'h18: y = 5'h10;  5'h19: y = 5'h0c;  5'h1a: y = 5'h01;  5'h1b: y = 5'h19;
            5'h1c: y = 5'h16;  5'h1d: y = 5'h0a;  5'h1e: y = 5'h0f;  5'h1f: y = 5'h17;
        endcase
    end
endmodule

// Wraps the bitsliced S-box with the same 5-bit port as the reference, so the
// two can be compared directly.
module ascon_sbox_dut (
    input  wire [4:0] x,
    output wire [4:0] y
);
    ascon_sbox #(.W(1)) u (
        .x0(x[4]), .x1(x[3]), .x2(x[2]), .x3(x[1]), .x4(x[0]),
        .y0(y[4]), .y1(y[3]), .y2(y[2]), .y3(y[1]), .y4(y[0])
    );
endmodule
