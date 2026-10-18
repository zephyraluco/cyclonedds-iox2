fn main() {
    let dir = std::env::var("BENCH_NATIVE_DIR")
        .expect("set BENCH_NATIVE_DIR to the CMake benchmark build directory");
    println!("cargo:rustc-link-search=native={dir}");
    println!("cargo:rustc-link-lib=dylib=bench_types");
    println!("cargo:rerun-if-env-changed=BENCH_NATIVE_DIR");
}
