//! A deliberately separate high-level API probe; never report its UDP fallback
//! or unsupported PSMX callbacks as the sys-binding zero-copy benchmark.
use cyclonedds::qos::policy;
use cyclonedds::sample::View;
use cyclonedds::{Domain, Duration, Participant, QoS, Reader, Topic, Topicable, Writer};
use std::time::{Duration as StdDuration, Instant};

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, Default)]
struct Small {
    seq: u64,
    payload: [[u8; 8]; 7],
}
impl Topicable for Small {
    type Key = ();
    fn from_key(_: &()) -> Self {
        Self::default()
    }
    fn as_key(&self) {}
    fn dds_type_name() -> impl AsRef<str> {
        "ShmBench::Small"
    }
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a: Vec<String> = std::env::args().collect();
    if a.len() != 3 || !["server", "client"].contains(&a[1].as_str()) {
        return Err("usage: high_level_probe client|server SESSION".into());
    }
    let config = std::fs::read_to_string(std::env::var("CYCLONEDDS_URI")?)?;
    let domain = Domain::new_with_xml_config(73, &config)?;
    let participant = Participant::new(&domain)?;
    let req = Topic::<Small>::new(&participant, &format!("Probe_{}_request", a[2]))?;
    let rep = Topic::<Small>::new(&participant, &format!("Probe_{}_reply", a[2]))?;
    let server = a[1] == "server";
    let qos = QoS::new()
        .with_history(policy::History::KeepLast { depth: 64 })
        .with_durability(policy::Durability::Volatile)
        .with_reliability(policy::Reliability::Reliable {
            max_blocking_time: Duration::from_secs(5),
        });
    let writer = Writer::builder(if server { &rep } else { &req })
        .with_qos(&qos)
        .build()?;
    let reader = Reader::builder(if server { &req } else { &rep })
        .with_qos(&qos)
        .build()?;
    let deadline = Instant::now() + StdDuration::from_secs(5);
    while writer.matched_subscriptions()?.is_empty() || reader.matched_publications()?.is_empty() {
        if Instant::now() >= deadline {
            return Err("high-level discovery timeout".into());
        }
        std::thread::sleep(StdDuration::from_millis(5));
    }
    let sample = Small {
        seq: 42,
        payload: [[0xa5; 8]; 7],
    };
    if !server {
        writer.write(&sample)?;
    }
    let deadline = Instant::now() + StdDuration::from_secs(3);
    loop {
        for received in reader.take()? {
            if let View::Sample(value) = received.view() {
                if value.seq != 42 || value.payload != sample.payload {
                    return Err("corrupt sample".into());
                }
                if server {
                    writer.write(&sample)?;
                    let deadline = Instant::now() + StdDuration::from_secs(5);
                    while !writer.matched_subscriptions()?.is_empty() {
                        if Instant::now() >= deadline {
                            return Err("peer close timeout".into());
                        }
                        std::thread::sleep(StdDuration::from_millis(5));
                    }
                }
                println!("high-level roundtrip passed");
                return Ok(());
            }
        }
        if Instant::now() >= deadline {
            return Err("high-level receive timeout (inspect PSMX callback logs)".into());
        }
        std::thread::sleep(StdDuration::from_millis(1));
    }
}
