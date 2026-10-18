#define _POSIX_C_SOURCE 200809L
#include "endpoint.h"
#include "Sample.h"
#include <dds/dds.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct bench_endpoint {
  dds_entity_t participant, writer, reader, waitset;
  bench_options options;
  void *sample;
  unsigned char expected[65528];
};

void bench_require(int ok, const char *message) {
  if (!ok) { fprintf(stderr, "benchmark error: %s\n", message); exit(2); }
}
static void check(dds_return_t rc, const char *operation) {
  if (rc < 0) { fprintf(stderr, "%s: %s\n", operation, dds_strretcode(rc)); exit(2); }
}
uint64_t bench_now(void) {
  struct timespec ts;
  bench_require(clock_gettime(CLOCK_MONOTONIC, &ts) == 0, "clock_gettime");
  return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}
static int number(const char *s) {
  char *end;
  long value = strtol(s, &end, 10);
  bench_require(*s && !*end && value >= 0 && value <= 1000000, "invalid numeric argument");
  return (int)value;
}
bench_options bench_parse(int argc, char **argv) {
  bench_require(argc == 10, "usage: PROGRAM client|server SIZE COUNT WARMUP WINDOW LOAN SHM DOMAIN SESSION");
  bench_require(!strcmp(argv[1], "client") || !strcmp(argv[1], "server"), "invalid role");
  bench_options o = { !strcmp(argv[1], "server"), number(argv[2]), number(argv[3]),
    number(argv[4]), number(argv[5]), number(argv[6]), number(argv[7]), number(argv[8]), argv[9] };
  bench_require(o.size == 64 || o.size == 4096 || o.size == 65536, "unsupported size");
  bench_require(o.count > 0 && o.window > 0 && o.window <= 16 && o.domain <= 200 &&
                o.loan <= 1 && o.shm <= 1 && (!o.loan || o.shm), "invalid benchmark options");
  bench_require(strlen(o.session) < 80, "session name too long");
  return o;
}
bench_endpoint *bench_open(const bench_options *o) {
  bench_endpoint *ep = calloc(1, sizeof(*ep));
  bench_require(ep != NULL, "allocation");
  ep->options = *o;
  memset(ep->expected, 0xa5, sizeof(ep->expected));
  const dds_topic_descriptor_t *desc = o->size == 64 ? &ShmBench_Small_desc :
    o->size == 4096 ? &ShmBench_Medium_desc : &ShmBench_Large_desc;
  bench_require((int)desc->m_size == o->size, "generated sample layout mismatch");
  ep->sample = calloc(1, desc->m_size);
  bench_require(ep->sample != NULL, "sample allocation");
  ep->participant = dds_create_participant((dds_domainid_t)o->domain, NULL, NULL);
  check(ep->participant, "create participant");
  char names[2][128];
  snprintf(names[0], sizeof(names[0]), "Bench_%s_request", o->session);
  snprintf(names[1], sizeof(names[1]), "Bench_%s_reply", o->session);
  dds_entity_t topics[2];
  for (int i = 0; i < 2; ++i) {
    topics[i] = dds_create_topic(ep->participant, desc, names[i], NULL, NULL);
    check(topics[i], "create topic");
  }
  dds_qos_t *qos = dds_create_qos();
  dds_qset_reliability(qos, DDS_RELIABILITY_RELIABLE, DDS_SECS(5));
  dds_qset_durability(qos, DDS_DURABILITY_VOLATILE);
  dds_qset_history(qos, DDS_HISTORY_KEEP_LAST, 64);
  ep->writer = dds_create_writer(ep->participant, topics[o->server ? 1 : 0], qos, NULL);
  ep->reader = dds_create_reader(ep->participant, topics[o->server ? 0 : 1], qos, NULL);
  dds_delete_qos(qos);
  check(ep->writer, "create writer"); check(ep->reader, "create reader");
  bench_require(dds_is_shared_memory_available(ep->writer) == (bool)o->shm,
                "writer shared-memory capability differs from requested transport");
  bench_require(dds_is_shared_memory_available(ep->reader) == (bool)o->shm,
                "reader shared-memory capability differs from requested transport");
  ep->waitset = dds_create_waitset(ep->participant);
  check(ep->waitset, "create waitset");
  dds_entity_t cond = dds_create_readcondition(ep->reader, DDS_ANY_STATE);
  check(cond, "create read condition");
  check(dds_waitset_attach(ep->waitset, cond, 1), "attach read condition");
  const uint64_t deadline = bench_now() + UINT64_C(15000000000);
  for (;;) {
    int32_t writers = dds_get_matched_publications(ep->reader, NULL, 0);
    int32_t readers = dds_get_matched_subscriptions(ep->writer, NULL, 0);
    check(writers, "matched publications"); check(readers, "matched subscriptions");
    if (writers > 0 && readers > 0) break;
    bench_require(bench_now() < deadline, "discovery timeout");
    dds_sleepfor(DDS_MSECS(5));
  }
  return ep;
}
void bench_send(bench_endpoint *ep, uint64_t seq) {
  void *sample = ep->sample;
  if (ep->options.loan) check(dds_request_loan(ep->writer, &sample), "request writer loan");
  memcpy(sample, &seq, sizeof(seq));
  memset((unsigned char *)sample + sizeof(seq), 0xa5, (size_t)ep->options.size - sizeof(seq));
  dds_return_t rc = dds_write(ep->writer, sample);
  if (rc < 0 && ep->options.loan) (void)dds_return_loan(ep->writer, &sample, 1);
  check(rc, "write"); /* successful write consumes a writer loan */
}
uint64_t bench_receive(bench_endpoint *ep) {
  const uint64_t deadline = bench_now() + UINT64_C(10000000000);
  for (;;) {
    void *sample = NULL;
    dds_sample_info_t info;
    int32_t n = dds_take(ep->reader, &sample, &info, 1, 1);
    check(n, "take");
    if (n) {
      uint64_t seq = 0;
      int valid = info.valid_data;
      if (valid) {
        memcpy(&seq, sample, sizeof(seq));
        valid = memcmp((unsigned char *)sample + sizeof(seq), ep->expected,
                       (size_t)ep->options.size - sizeof(seq)) == 0;
      }
      check(dds_return_loan(ep->reader, &sample, n), "return reader loan");
      if (info.valid_data) { bench_require(valid, "corrupt payload"); return seq; }
    }
    bench_require(bench_now() < deadline, "sample receive timeout");
    dds_attach_t trigger;
    check(dds_waitset_wait(ep->waitset, &trigger, 1, DDS_MSECS(100)), "wait for data");
  }
}
void bench_close(bench_endpoint *ep) {
  if (ep->options.server) {
    uint64_t deadline = bench_now() + UINT64_C(10000000000);
    while (dds_get_matched_subscriptions(ep->writer, NULL, 0) > 0) {
      bench_require(bench_now() < deadline, "peer did not close after completion");
      dds_sleepfor(DDS_MSECS(5));
    }
  }
  check(dds_delete(ep->participant), "delete participant");
  free(ep->sample); free(ep);
}
static int compare_u64(const void *a, const void *b) {
  uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
  return (x > y) - (x < y);
}
void bench_report(const char *language, const bench_options *o, uint64_t elapsed, uint64_t *rtt) {
  qsort(rtt, (size_t)o->count, sizeof(*rtt), compare_u64);
  double seconds = (double)elapsed / 1e9;
  printf("{\"language\":\"%s\",\"size_bytes\":%d,\"samples\":%d,\"warmup\":%d,"
    "\"window\":%d,\"loan\":%d,\"shm\":%d,\"elapsed_s\":%.9f,"
    "\"p50_rtt_us\":%.3f,\"p99_rtt_us\":%.3f,\"samples_per_s\":%.3f,"
    "\"payload_mib_per_s\":%.3f}\n", language, o->size, o->count, o->warmup, o->window,
    o->loan, o->shm, seconds, (double)rtt[(o->count - 1)/2]/1e3,
    (double)rtt[((size_t)o->count * 99 + 99)/100 - 1]/1e3,
    o->count/seconds, (double)o->count * o->size/seconds/1048576.0);
}
