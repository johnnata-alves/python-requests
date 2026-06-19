import json
import pandas as pd
from collections import defaultdict

def parse_logs(file_path):
    logs_summary = defaultdict(list)
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            try:
                log_entry = json.loads(line)
                
                component = log_entry.get("c", "UNKNOWN")
                namespace = log_entry.get("attr", {}).get("ns", "UNKNOWN")
                message = log_entry.get("msg", "UNKNOWN")
                timestamp = log_entry.get("t", {}).get("$date", "")
                
                logs_summary["component"].append(component)
                logs_summary["namespace"].append(namespace)
                logs_summary["message"].append(message)
                logs_summary["timestamp"].append(timestamp)
                
            except json.JSONDecodeError:
                print(f"Failed to parse line: {line}")
    
    return logs_summary

def save_to_excel(logs_summary, output_file):
    df = pd.DataFrame(logs_summary)
    
    df.to_excel(output_file, index=False)

if __name__ == "__main__":
    file_path = 'logs.txt'
    logs_summary = parse_logs(file_path)
    output_file = 'logs_report.xlsx'
    save_to_excel(logs_summary, output_file)
    print(f"Relatório salvo em {output_file}")
