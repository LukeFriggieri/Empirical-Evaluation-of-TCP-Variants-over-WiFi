import json
import csv
import subprocess
import time
import sys
import math
import os
from datetime import datetime
from pathlib import Path

class TCPVariantTester:
    def __init__(self, server_ip="10.0.0.2", test_duration=55, repetitions=3,
                 interface="wlx24ec99bfc42b"):
        self.server_ip = server_ip
        self.test_duration = test_duration
        self.repetitions = repetitions
        self.interface = interface
        self.tcp_variants = ['cubic', 'westwood', 'veno', 'vegas']
        self.all_results = []
        self.final_csv = "results/tcp_results_all_sessions.csv"
        self._emergency_save_needed = False
        self.setup_directories()

    def setup_directories(self):
        Path('results/json_files').mkdir(parents=True, exist_ok=True)
        Path('results/logs').mkdir(parents=True, exist_ok=True)

    # Inputs & Calculations

    def get_noise_input(self):
        """
        Get noise power P3 (dBm) at the START of the session.
        Measure with the Wi-Fi Tx OFF so only the noise source is active.
        """
        while True:
            try:
                return float(input(
                    " Enter noise power P3 (dBm) [measure with Wi-Fi Tx OFF]: "
                ).strip())
            except ValueError:
                print(" Invalid value. Enter a numeric dBm value.")

    def get_sa_reading(self, variant=None):
        """Prompt for the SA Channel Power reading at the END of a variant's tests."""
        if variant:
            print("\n" + "="*56)
            print(f" {variant.upper()} TESTS COMPLETE. SA READING REQUIRED.")
            print("="*56)
        while True:
            try:
                return float(input(
                    " Read SA Channel Power at difference port (dBm): "
                ).strip())
            except ValueError:
                print(" Invalid value. Enter a numeric dBm reading.")

    def calculate_snr(self, sa_reading_dbm, noise_dbm):
        """
        Calculate True SNR and True P1 using the provided equation.
        """
        try:
            # S-parameters (dB)
            S41_dB = -3.34  # Tx to Delta Port
            S43_dB = -3.37  # Noise to Delta Port
            S21_dB = -3.37  # Tx to Sigma (RX) Port
            S23_dB = -3.30  # Noise to Sigma (RX) Port

            # Convert dBm to linear power
            p_delta_lin = 10 ** (sa_reading_dbm / 10)
            p3_noise_lin = 10 ** (noise_dbm / 10)

            mag_sq_S41 = 10 ** (S41_dB / 10)
            mag_sq_S43 = 10 ** (S43_dB / 10)
            
            # Additional parameters needed for SNR calculation
            mag_sq_S21 = 10 ** (S21_dB / 10)
            mag_sq_S23 = 10 ** (S23_dB / 10)

            # Implement P1 = ( P_delta - |S43|^2 * P3 ) / |S41|^2
            p1_lin = (p_delta_lin - (mag_sq_S43 * p3_noise_lin)) / mag_sq_S41

            if p1_lin <= 0:
                print(" WARNING: Calculated linear P1 is <= 0. Cannot compute logarithm.")
                return None, None

            p_rx_signal_lin = mag_sq_S21 * p1_lin
            p_rx_noise_lin = mag_sq_S23 * p3_noise_lin

            true_p1_dbm = 10 * math.log10(p1_lin)
            true_snr_lin = p_rx_signal_lin / p_rx_noise_lin
            true_snr_db = 10 * math.log10(true_snr_lin)

            return round(true_snr_db, 2), round(true_p1_dbm, 2)

        except Exception as e:
            print(f" Error calculating SNR: {e}")
            return None, None

    # TCP / iperf3 helpers

    def set_tcp_variant(self, variant):
        try:
            result = subprocess.run(
                f'sudo sysctl -w net.ipv4.tcp_congestion_control={variant}',
                shell=True, capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_interface_ip(self):
        try:
            result = subprocess.run(
                ['ip', 'addr', 'show', self.interface],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line and '127.0.0.1' not in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            return parts[1].split('/')[0]
            return None
        except Exception as e:
            print(f' Error getting interface IP: {e}')
            return None

    def run_iperf3_test(self, tcp_variant, repetition, noise_dbm):
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        json_filename = f"SNR_PENDING_normal_iperf3_{tcp_variant}_rep{repetition}_{timestamp}.json"
        json_filepath = f"results/json_files/{json_filename}"
        
        try:
            interface_ip = self.get_interface_ip()
            if interface_ip is None:
                print(f' ERROR: No IP found on {self.interface}.')
                return None
                
            cmd = [
                'iperf3', '-c', self.server_ip,
                '-t', str(self.test_duration),
                '-B', interface_ip,
                '-C', tcp_variant,
                '-J', '--get-server-output'
            ]
            
            print(f' Running {tcp_variant} | rep {repetition} ({self.test_duration}s)')
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=self.test_duration + 45)
            
            if result.returncode != 0:
                print(f' iperf3 failed: {result.stderr.strip()}')
                return None
                
            test_data = json.loads(result.stdout)
            with open(json_filepath, 'w') as f:
                json.dump(test_data, f, indent=2)
                
            end_stats = test_data.get('end', {})
            sum_sent = end_stats.get('sum_sent', {})
            sum_received = end_stats.get('sum_received', {})
            sender_streams = end_stats.get('streams', [])
            sender_stats = sender_streams[0].get('sender', {}) if sender_streams else {}
            
            throughput_mbps = sum_received.get('bits_per_second', 0) / 1_000_000
            mean_rtt_us = sender_stats.get('mean_rtt', 0)
            avg_rtt_ms = mean_rtt_us / 1000 if mean_rtt_us else 0
            retransmissions = sender_stats.get('retransmits', 0)
            max_rtt_ms = (sender_stats.get('max_rtt', 0) / 1000 
                          if sender_stats.get('max_rtt') else 0)
            min_rtt_ms = (sender_stats.get('min_rtt', 0) / 1000 
                          if sender_stats.get('min_rtt') else 0)
            actual_cc = end_stats.get('sender_tcp_congestion', 'unknown')
            
            row = {
                'timestamp': timestamp,
                'tcp_variant': tcp_variant,
                'test_condition': 'normal',
                'repetition': repetition,
                'snr_db': None,
                'sa_delta_dbm': None,
                'p1_dbm': None,
                'p3_noise_dbm': noise_dbm,
                'throughput_mbps': round(throughput_mbps, 2),
                'rtt_ms': round(avg_rtt_ms, 2),
                'retransmissions': retransmissions,
                'duration_sec': sum_sent.get('seconds', 0),
                'bytes_sent': sum_sent.get('bytes', 0),
                'bytes_received': sum_received.get('bytes', 0),
                'max_rtt_ms': round(max_rtt_ms, 2),
                'min_rtt_ms': round(min_rtt_ms, 2),
                'tcp_congestion': actual_cc,
                'json_filename': json_filename,
                '_temp_filepath': json_filepath
            }
            
            print(f' Done - {row["throughput_mbps"]} Mbps | '
                  f'RTT {row["rtt_ms"]} ms | retrans {row["retransmissions"]}')
            
            if actual_cc.lower() != tcp_variant.lower():
                print(f' WARNING: Requested {tcp_variant} '
                      f'but iperf3 reports it used {actual_cc}!')
                
            return row
            
        except json.JSONDecodeError:
            print(' Failed to parse iperf3 JSON output.')
            return None
        except subprocess.TimeoutExpired:
            print(' iperf3 timed out.')
            return None
        except Exception as e:
            print(f' Error running test: {e}')
            return None

    # CSV writing

    HEADERS = [
        'timestamp', 'tcp_variant', 'test_condition', 'repetition',
        'snr_db', 'sa_delta_dbm', 'p1_dbm', 'p3_noise_dbm',
        'throughput_mbps', 'rtt_ms', 'retransmissions',
        'duration_sec', 'bytes_sent', 'bytes_received',
        'max_rtt_ms', 'min_rtt_ms', 'tcp_congestion', 'json_filename'
    ]

    def _row_to_list(self, row):
        return [row[h] for h in self.HEADERS if h in row]

    def append_row_to_final_csv(self, row):
        file_exists = Path(self.final_csv).exists()
        with open(self.final_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(self.HEADERS)
            writer.writerow(self._row_to_list(row))

    def update_csv_with_final_snr(self, session_rows):
        if not Path(self.final_csv).exists():
            return
            
        timestamps_to_update = {r['timestamp']: r for r in session_rows}
        updated_rows = []
        
        with open(self.final_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for file_row in reader:
                ts = file_row['timestamp']
                if ts in timestamps_to_update:
                    update_data = timestamps_to_update[ts]
                    file_row['snr_db'] = update_data['snr_db']
                    file_row['sa_delta_dbm'] = update_data['sa_delta_dbm']
                    file_row['p1_dbm'] = update_data['p1_dbm']
                    file_row['json_filename'] = update_data['json_filename']
                updated_rows.append(file_row)
                
        with open(self.final_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writeheader()
            writer.writerows(updated_rows)

    def emergency_save(self):
        if not self._emergency_save_needed:
            return
        print(' Running emergency save...')
        file_exists = Path(self.final_csv).exists()
        with open(self.final_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(self.HEADERS)
            for row in self.all_results:
                writer.writerow(self._row_to_list(row))
        print(f' Saved to {self.final_csv}')

    # Session control

    def run_single_session(self, noise_dbm):
        print('')
        print(f' Session start - P3 {noise_dbm} dBm')
        
        input(' Ensure iperf3 -s is running on the server. Press Enter...')
        
        for tcp_variant in self.tcp_variants:
            print(f'\n [ {tcp_variant.upper()} ]')
            self.set_tcp_variant(tcp_variant)
            time.sleep(1)
            
            variant_rows = []
            sa_readings_dbm = []

            for rep in range(1, self.repetitions + 1):
                self._emergency_save_needed = True
                row = self.run_iperf3_test(tcp_variant, rep, noise_dbm)

                if row:
                    sa_reading = self.get_sa_reading(variant=tcp_variant)
                    sa_readings_dbm.append(sa_reading)

                    input("\n Press Enter when buffer is cleared...")

                    self.all_results.append(row)
                    variant_rows.append(row)
                    self.append_row_to_final_csv(row)
                    self._emergency_save_needed = False
                else:
                    print(f' Test failed: {tcp_variant} rep {rep}')

                if rep < self.repetitions:
                    time.sleep(5)

            # Average the SA readings in linear power
            if sa_readings_dbm:
                linear_powers = [10 ** (r / 10) for r in sa_readings_dbm]
                avg_linear_power = sum(linear_powers) / len(linear_powers)
                avg_sa_reading_dbm = 10 * math.log10(avg_linear_power)

                snr_db, p1_dbm = self.calculate_snr(avg_sa_reading_dbm, noise_dbm)

                if snr_db is None:
                    print(" Failed to calculate SNR. CSV contains 'None' for these fields.")
                else:
                    print(f'\n --- Calculations for {tcp_variant.upper()} ---')
                    print(f' Raw SA Delta readings: {sa_readings_dbm}')
                    print(f' Averaged SA Delta reading : {round(avg_sa_reading_dbm, 2)} dBm')
                    print(f' True P1 (signal) : {p1_dbm} dBm')
                    print(f' True SNR         : {snr_db} dB')

                    print(f' Backfilling SNR data for {tcp_variant.upper()} into CSV and renaming JSON files...')
                    for row in variant_rows:
                        row['snr_db'] = snr_db
                        row['sa_delta_dbm'] = round(avg_sa_reading_dbm, 2)
                        row['p1_dbm'] = p1_dbm

                        old_filepath = Path(row['_temp_filepath'])
                        new_filename = f"SNR{snr_db}_normal_iperf3_{row['tcp_variant']}_rep{row['repetition']}_{row['timestamp']}.json"
                        new_filepath = old_filepath.parent / new_filename

                        if old_filepath.exists():
                            os.rename(old_filepath, new_filepath)

                        row['json_filename'] = new_filename

                    self.update_csv_with_final_snr(variant_rows)
                    print(' Data successfully updated for this variant.')
            else:
                print(' No successful tests to average.')

            time.sleep(5)
                    
            sa_reading = self.get_sa_reading(variant=tcp_variant)

            input("\n Press Enter when buffer is cleared...")
            
            snr_db, p1_dbm = self.calculate_snr(sa_reading, noise_dbm)
            
            if snr_db is None:
                print(" Failed to calculate SNR. CSV contains 'None' for these fields.")
            else:
                print(f'\n --- Calculations for {tcp_variant.upper()} ---')
                print(f' SA Delta reading     : {sa_reading} dBm')
                print(f' True P1 (signal) : {p1_dbm} dBm')
                print(f' True SNR         : {snr_db} dB')
                
                print(f' Backfilling SNR data for {tcp_variant.upper()} into CSV and renaming JSON files...')
                for row in variant_rows:
                    row['snr_db'] = snr_db
                    row['sa_delta_dbm'] = sa_reading
                    row['p1_dbm'] = p1_dbm
                    
                    old_filepath = Path(row['_temp_filepath'])
                    new_filename = f"SNR{snr_db}_normal_iperf3_{row['tcp_variant']}_rep{row['repetition']}_{row['timestamp']}.json"
                    new_filepath = old_filepath.parent / new_filename
                    
                    if old_filepath.exists():
                        os.rename(old_filepath, new_filepath)
                    
                    row['json_filename'] = new_filename
                    
                self.update_csv_with_final_snr(variant_rows)
                print(' Data successfully updated for this variant.')
                
            time.sleep(5)

    def start_interactive(self):
        print('')
        print(' TCP Variant Tester - Normal Condition')
        
        print(' Server setup required:')
        print(' iperf3 -s (leave running throughout)')
        print('='*56 + '\n')
        
        try:
            while True:
                print('\n--- New Session ---')
                noise_dbm = self.get_noise_input()
                
                self.run_single_session(noise_dbm)
                
                again = input('\nRun another session at a different SNR? (y/N): ').strip().lower()
                if again != 'y':
                    break
                    
            print(f'\nAll done. Results saved to {self.final_csv}')
            
        except KeyboardInterrupt:
            print('\n\nInterrupted by user.')
            self.emergency_save()
            sys.exit(1)

def main():
    SERVER_IP = "10.0.0.2"
    INTERFACE = "wlx24ec99bfc42b"
    TEST_DURATION = 55
    REPETITIONS = 5
    
    tester = TCPVariantTester(
        server_ip=SERVER_IP,
        test_duration=TEST_DURATION,
        repetitions=REPETITIONS,
        interface=INTERFACE
    )
    
    tester.start_interactive()

if __name__ == "__main__":
    main()