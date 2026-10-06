// Demo fixture: a small Rust module with intentional issues.
use std::process::Command;

pub struct Config {
    pub endpoint: String,
}

impl Config {
    /// Intentional finding: RS-UNWRAP (CWE-248)
    pub fn from_env() -> Config {
        let endpoint = std::env::var("DEMO_ENDPOINT").unwrap();
        Config { endpoint }
    }

    /// Intentional finding: RS-COMMAND (CWE-78)
    pub fn run_hook(&self, script: &str) -> std::io::Result<()> {
        Command::new("sh").arg("-c").arg(script).status()?;
        Ok(())
    }
}

pub fn checksum(values: &[u32]) -> u32 {
    values.iter().fold(0u32, |acc, value| acc.wrapping_add(*value))
}
