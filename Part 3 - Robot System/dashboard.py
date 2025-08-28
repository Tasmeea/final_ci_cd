import pandas as pd
import json
import os
from datetime import datetime, timedelta
import numpy as np

class DashboardManager:
    def __init__(self):
        self.robot_sensor_data = {}
        self.latest_sensor_readings = {}
    
    def update_robot_data(self, robot_id, sensor_data):
        """Update robot sensor data"""
        if robot_id not in self.robot_sensor_data:
            self.robot_sensor_data[robot_id] = []
        
        self.robot_sensor_data[robot_id].append(sensor_data)
        self.latest_sensor_readings[robot_id] = sensor_data
        
        # Keep only last 1000 readings per robot
        if len(self.robot_sensor_data[robot_id]) > 1000:
            self.robot_sensor_data[robot_id] = self.robot_sensor_data[robot_id][-1000:]
    
    def get_latest_sensor_data(self):
        """Get latest sensor data from all robots"""
        return self.latest_sensor_readings
    
    def get_sensor_history(self, robot_id, hours=24):
        """Get sensor history for a specific robot"""
        if robot_id not in self.robot_sensor_data:
            return []
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        filtered_data = [
            reading for reading in self.robot_sensor_data[robot_id]
            if datetime.fromisoformat(reading['timestamp']) > cutoff_time
        ]
        
        return filtered_data
    
    def get_floor_analytics(self):
        """Get analytics by floor"""
        floor_data = {}
        
        for robot_id, readings in self.robot_sensor_data.items():
            if not readings:
                continue
                
            latest = readings[-1]
            floor = latest['floor']
            
            if floor not in floor_data:
                floor_data[floor] = {
                    'temperature': [],
                    'humidity': [],
                    'air_quality': [],
                    'noise_level': [],
                    'motion_events': 0
                }
            
            # Get recent readings for this floor
            recent_readings = [r for r in readings[-50:] if r['floor'] == floor]
            
            for reading in recent_readings:
                floor_data[floor]['temperature'].append(reading['temperature'])
                floor_data[floor]['humidity'].append(reading['humidity'])
                floor_data[floor]['air_quality'].append(reading['air_quality'])
                floor_data[floor]['noise_level'].append(reading['noise_level'])
                if reading.get('motion_detected'):
                    floor_data[floor]['motion_events'] += 1
        
        # Calculate averages
        analytics = {}
        for floor, data in floor_data.items():
            analytics[floor] = {
                'avg_temperature': np.mean(data['temperature']) if data['temperature'] else 0,
                'avg_humidity': np.mean(data['humidity']) if data['humidity'] else 0,
                'avg_air_quality': np.mean(data['air_quality']) if data['air_quality'] else 0,
                'avg_noise_level': np.mean(data['noise_level']) if data['noise_level'] else 0,
                'motion_events': data['motion_events'],
                'status': 'normal'  # Could add logic for status determination
            }
        
        return analytics