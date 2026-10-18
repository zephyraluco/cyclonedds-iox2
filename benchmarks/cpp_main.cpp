#include "endpoint.h"
#include "Sample.hpp"
#include <dds/dds.hpp>
#include <dds/dds.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

static void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}

template<class T> class Endpoint {
  bench_options options;
  dds::domain::DomainParticipant participant;
  dds::topic::Topic<T> request, reply;
  dds::pub::Publisher publisher;
  dds::sub::Subscriber subscriber;
  dds::pub::DataWriter<T> writer;
  dds::sub::DataReader<T> reader;
  dds::sub::cond::ReadCondition condition;
  dds::core::cond::WaitSet waitset;
  T sample;
  std::vector<uint8_t> expected;
  static dds::pub::qos::DataWriterQos writer_qos(const dds::pub::Publisher &p) {
    auto qos = p.default_datawriter_qos();
    qos << dds::core::policy::Reliability::Reliable(dds::core::Duration::from_secs(5))
        << dds::core::policy::Durability::Volatile()
        << dds::core::policy::History::KeepLast(64);
    return qos;
  }
  static dds::sub::qos::DataReaderQos reader_qos(const dds::sub::Subscriber &s) {
    auto qos = s.default_datareader_qos();
    qos << dds::core::policy::Reliability::Reliable(dds::core::Duration::from_secs(5))
        << dds::core::policy::Durability::Volatile()
        << dds::core::policy::History::KeepLast(64);
    return qos;
  }
public:
  explicit Endpoint(const bench_options &o) : options(o), participant(o.domain),
    request(participant, std::string("Bench_") + o.session + "_request"),
    reply(participant, std::string("Bench_") + o.session + "_reply"),
    publisher(participant), subscriber(participant),
    writer(publisher, o.server ? reply : request, writer_qos(publisher)),
    reader(subscriber, o.server ? request : reply, reader_qos(subscriber)),
    condition(reader, dds::sub::status::DataState::any()), expected(sample.payload().size(), 0xa5) {
    /* Native entity access and writer loans are CycloneDDS-cxx extensions. */
    require(dds_is_shared_memory_available(writer.delegate()->get_ddsc_entity()) == !!o.shm,
            "C++ writer shared-memory capability mismatch");
    require(dds_is_shared_memory_available(reader.delegate()->get_ddsc_entity()) == !!o.shm,
            "C++ reader shared-memory capability mismatch");
    require(!o.loan || writer.delegate()->is_loan_supported(), "C++ writer does not support loans");
    waitset.attach_condition(condition);
    auto deadline = bench_now() + UINT64_C(15000000000);
    while (writer.publication_matched_status().current_count() == 0 ||
           reader.subscription_matched_status().current_count() == 0) {
      require(bench_now() < deadline, "C++ discovery timeout");
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }
  void send(uint64_t seq) {
    T &value = options.loan ? writer.delegate()->loan_sample() : sample;
    value.seq(seq);
    std::fill(value.payload().begin(), value.payload().end(), uint8_t{0xa5});
    try { writer.write(value); }
    catch (...) { if (options.loan) writer.delegate()->return_loan(value); throw; }
  }
  uint64_t receive() {
    auto deadline = bench_now() + UINT64_C(10000000000);
    for (;;) {
      // One sample at a time, matching the C and Rust workload.
      auto samples = reader.select().max_samples(1).take();
      for (const auto &value : samples) {
        if (!value.info().valid()) continue;
        const auto &data = value.data();
        require(std::memcmp(data.payload().data(), expected.data(), expected.size()) == 0,
                "C++ corrupt payload");
        return data.seq(); // LoanedSamples returns the reader loan through RAII.
      }
      require(bench_now() < deadline, "C++ receive timeout");
      try { waitset.wait(dds::core::Duration::from_millisecs(100)); }
      catch (const dds::core::TimeoutError &) { /* bounded overall deadline above */ }
    }
  }
  void wait_for_peer_close() {
    auto deadline = bench_now() + UINT64_C(10000000000);
    while (writer.publication_matched_status().current_count() > 0) {
      require(bench_now() < deadline, "C++ peer did not close after completion");
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }
};

template<class T> static void run(const bench_options &o) {
  Endpoint<T> endpoint(o);
  std::cout << "DISCOVERED" << std::endl;
  require(std::cin.get() == '\n', "C++ missing peer discovery barrier");
  if (o.server) {
    for (int i = 0; i < o.count + o.warmup; ++i) {
      auto seq = endpoint.receive();
      require(seq == static_cast<uint64_t>(i), "C++ server sequence mismatch");
      endpoint.send(seq);
    }
    require(endpoint.receive() == UINT64_MAX, "C++ completion handshake missing");
    endpoint.send(UINT64_MAX);
    endpoint.wait_for_peer_close();
  } else {
    std::vector<uint64_t> rtt(static_cast<size_t>(o.count));
    auto phase = [&](int first, int count, bool measured) {
      std::array<uint64_t,16> starts{};
      for (int base = 0; base < count; base += o.window) {
        int batch = std::min(o.window, count-base);
        for (int j = 0; j < batch; ++j) {
          starts[j] = bench_now(); endpoint.send(static_cast<uint64_t>(first+base+j));
        }
        for (int j = 0; j < batch; ++j) {
          auto seq = endpoint.receive(); auto end = bench_now();
          require(seq == static_cast<uint64_t>(first+base+j), "C++ sequence mismatch");
          if (measured) rtt[base+j] = end-starts[j];
        }
      }
    };
    phase(0, o.warmup, false);
    std::cout << "READY" << std::endl;
    require(std::cin.get() == '\n', "C++ missing measurement start signal");
    auto start = bench_now();
    phase(o.warmup, o.count, true);
    auto elapsed = bench_now()-start;
    endpoint.send(UINT64_MAX);
    require(endpoint.receive() == UINT64_MAX, "C++ completion acknowledgment missing");
    bench_report("cpp", &o, elapsed, rtt.data());
  }
}
int main(int argc, char **argv) {
  try {
    auto o = bench_parse(argc, argv);
    switch (o.size) {
      case 64: run<ShmBench::Small>(o); break;
      case 4096: run<ShmBench::Medium>(o); break;
      case 65536: run<ShmBench::Large>(o); break;
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n'; return 2;
  }
}
