/* Latency of ONE inference at a time (batch 1) on a desktop/laptop CPU, single thread. */
#include <stdio.h>
#include <time.h>
#include "model.h"
#include "net.h"
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
int main(void) {
    int bad = 0, k; signed char y[2];
    for (k = 0; k < NT; k++) { net_run(TIN[k], y); bad += (y[0] != TOUT[k][0]) || (y[1] != TOUT[k][1]); }
    printf("bit-exact check: %d/%d vectors match\n", NT - bad, NT);
    volatile int sink = 0; long n = 20000000; double best = 1e9;
    for (int rep = 0; rep < 5; rep++) {
        double t0 = now();
        for (long i = 0; i < n; i++) { net_run(TIN[i % NT], y); sink += y[0]; }
        double ns = (now() - t0) / n * 1e9;
        if (ns < best) best = ns;
    }
    printf("CPU, one inference at a time: %.1f ns (best of 5 x %ld runs)\n", best, n);
    return 0;
}
