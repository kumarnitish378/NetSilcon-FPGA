/* Bare-metal Cortex-M4 build: run the 576 test vectors once, then one timed inference. */
#include "model.h"
#include "net.h"
volatile int result_bad = -1;
volatile signed char out[2];
void __attribute__((noinline)) one(void) { signed char y[2]; net_run(TIN[0], y); out[0] = y[0]; out[1] = y[1]; }
void start(void) {
    int bad = 0; signed char y[2];
    for (int k = 0; k < NT; k++) { net_run(TIN[k], y); bad += (y[0] != TOUT[k][0]) || (y[1] != TOUT[k][1]); }
    result_bad = bad;
    one();
    for (;;) {}
}
