/* NetSilcon-6x4 network in plain C, bit-exact with rtl/nn_layer.v */
static const unsigned char SIZES[6] = {4, 6, 6, 6, 6, 2};
static void net_run(const unsigned char *x, signed char *y) {
    int a[6], o[6], n_in, n_out, wi = 0, bi = 0, l, j, i;
    for (i = 0; i < 4; i++) a[i] = x[i];
    for (l = 0; l < 5; l++) {
        n_in = SIZES[l]; n_out = SIZES[l + 1];
        for (j = 0; j < n_out; j++) {
            int acc = B[bi + j];
            const signed char *wr = &W[wi + j * n_in];
            for (i = 0; i < n_in; i++) acc += a[i] * wr[i];
            if (l < 4 && acc < 0) acc = 0;
            int s = SH[l];
            int v = (acc + (s ? (1 << (s - 1)) : 0)) >> s;
            if (l < 4) { if (v > 127) v = 127; }
            else { if (v > 127) v = 127; if (v < -128) v = -128; }
            o[j] = v;
        }
        for (j = 0; j < n_out; j++) a[j] = o[j];
        wi += n_in * n_out; bi += n_out;
    }
    y[0] = (signed char)a[0]; y[1] = (signed char)a[1];
}
