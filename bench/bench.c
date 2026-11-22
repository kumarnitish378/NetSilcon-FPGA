// Same bit-exact int8 math as rtl/ns64_engine.v and model/ns64.py, plain C, one inference at a time.
#include <stdio.h>
#include <time.h>
#include "net.h"
static void infer(const signed char *x, signed char *y) {
    int a[64], b[64], n_in = 16;
    for (int i = 0; i < 16; i++) a[i] = x[i];
    for (int l = 0; l < 7; l++) {
        int n_out = SZ[l + 1], s = SH[l];
        const signed char *w = WS[l];
        for (int j = 0; j < n_out; j++) {
            int acc = BS[l][j];
            for (int i = 0; i < n_in; i++) acc += a[i] * w[j * n_in + i];
            if (l < 6 && acc < 0) acc = 0;
            int v = (acc + (s ? 1 << (s - 1) : 0)) >> s;
            if (l < 6) b[j] = v > 127 ? 127 : v;
            else       b[j] = v > 127 ? 127 : (v < -128 ? -128 : v);
        }
        for (int j = 0; j < n_out; j++) a[j] = b[j];
        n_in = n_out;
    }
    for (int j = 0; j < 16; j++) y[j] = (signed char)a[j];
}
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
int main(void) {
    signed char y[16]; int bad = 0;
    for (int k = 0; k < NV; k++) { infer(TX[k], y); for (int j = 0; j < 16; j++) bad += y[j] != TY[k][j]; }
    printf("bit-exact check: %d golden vectors, %d wrong outputs\n", NV, bad);
    volatile int sink = 0;
    for (int rep = 0; rep < 3; rep++) {
        long n = 0; double t0 = now(), t;
        do { for (int k = 0; k < NV; k++) { infer(TX[k], y); sink += y[0]; } n += NV; t = now(); } while (t - t0 < 2.0);
        printf("run %d: %ld inferences in %.2f s = %.3f us per inference\n", rep + 1, n, t - t0, (t - t0) / n * 1e6);
    }
    return 0;
}
