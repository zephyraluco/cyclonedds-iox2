#include "endpoint.h"
#include <stdio.h>
#include <stdlib.h>

static void phase(bench_endpoint *ep, int first, int count, int window, uint64_t *rtt) {
  uint64_t starts[16];
  for (int base = 0; base < count; base += window) {
    int batch = count - base < window ? count - base : window;
    for (int j = 0; j < batch; ++j) {
      starts[j] = bench_now(); bench_send(ep, (uint64_t)(first + base + j));
    }
    for (int j = 0; j < batch; ++j) {
      uint64_t seq = bench_receive(ep);
      uint64_t end = bench_now();
      bench_require(seq == (uint64_t)(first + base + j), "sequence gap, duplicate, or reordering");
      if (rtt) rtt[base+j] = end - starts[j];
    }
  }
}
int main(int argc, char **argv) {
  bench_options o = bench_parse(argc, argv);
  bench_endpoint *ep = bench_open(&o);
  puts("DISCOVERED"); fflush(stdout);
  bench_require(getchar() == '\n', "missing peer discovery barrier");
  if (o.server) {
    for (int i = 0; i < o.count + o.warmup; ++i) {
      uint64_t seq = bench_receive(ep);
      bench_require(seq == (uint64_t)i, "server sequence mismatch");
      bench_send(ep, seq);
    }
    /* The peer has received the last reply before announcing completion. */
    bench_require(bench_receive(ep) == UINT64_MAX, "missing completion handshake");
    bench_send(ep, UINT64_MAX);
  } else {
    uint64_t *rtt = calloc((size_t)o.count, sizeof(*rtt));
    bench_require(rtt != NULL, "RTT allocation");
    phase(ep, 0, o.warmup, o.window, NULL);
    puts("READY"); fflush(stdout);
    bench_require(getchar() == '\n', "missing measurement start signal");
    uint64_t start = bench_now();
    phase(ep, o.warmup, o.count, o.window, rtt);
    uint64_t elapsed = bench_now() - start;
    bench_send(ep, UINT64_MAX);
    bench_require(bench_receive(ep) == UINT64_MAX, "missing completion acknowledgment");
    bench_report("c", &o, elapsed, rtt);
    free(rtt);
  }
  bench_close(ep);
  return 0;
}
