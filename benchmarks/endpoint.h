#ifndef SHM_BENCH_ENDPOINT_H
#define SHM_BENCH_ENDPOINT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Common C endpoint and statistics helpers; C++ uses its own native endpoint. */
typedef struct bench_endpoint bench_endpoint;
typedef struct bench_options {
  int server, size, count, warmup, window, loan, shm, domain;
  const char *session;
} bench_options;
bench_options bench_parse(int argc, char **argv);
uint64_t bench_now(void);
void bench_require(int condition, const char *message);
bench_endpoint *bench_open(const bench_options *options);
void bench_send(bench_endpoint *endpoint, uint64_t seq);
uint64_t bench_receive(bench_endpoint *endpoint);
void bench_close(bench_endpoint *endpoint);
void bench_report(const char *language, const bench_options *options,
                  uint64_t elapsed_ns, uint64_t *rtt_ns);
#ifdef __cplusplus
}
#endif
#endif
