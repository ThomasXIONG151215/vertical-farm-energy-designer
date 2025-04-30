    def calculate_power_flows(self, 
                            available_power: np.ndarray, 
                            load_profile: np.ndarray, 
                            E_bat: float, 
                            use_gpu: bool = False) -> Dict[str, np.ndarray]:
        """
        Calculate battery power flows considering power balance
        
        Args:
            available_power: Available PV power at each time step
            load_profile: Load demand at each time step
            E_bat: Battery capacity in kWh
            use_gpu: Whether to use GPU acceleration
        
        Returns:
            Dictionary of battery performance metrics
        """
        # Check for zero battery capacity
        if E_bat <= 0:
            n_steps = len(load_profile)
            return {
                'battery_power': np.zeros(n_steps),
                'battery_energy': np.zeros(n_steps + 1),
                'battery_soc': np.zeros(n_steps + 1),
                'battery_throughput': 0.0
            }
        
        # Battery parameters
        max_charge_rate = E_bat * 0.2  # C-rate limit of 0.2
        max_discharge_rate = E_bat * 0.2
        eta_ch = 0.95  # Charging efficiency
        eta_dch = 0.95  # Discharging efficiency
        self_discharge_rate = 0.0009  # Daily self-discharge rate
        
        # Initialize arrays
        n_steps = len(load_profile)
        battery_power = np.zeros(n_steps)
        battery_energy = np.zeros(n_steps + 1)
        battery_soc = np.zeros(n_steps + 1)
        
        # Initial SOC at 50%
        battery_energy[0] = E_bat * 0.5
        battery_soc[0] = 0.5
        
        # Battery throughput tracking
        battery_throughput = 0.0
        
        for t in range(n_steps):
            # Calculate power balance (PV power - load)
            power_balance = available_power[t] - load_profile[t]
            
            # Apply self-discharge
            battery_energy[t] *= (1 - self_discharge_rate)
            battery_soc[t] = battery_energy[t] / E_bat
            
            # Charging logic
            if power_balance > 0 and battery_soc[t] < 0.9:
                # Determine maximum possible charge
                max_charge = min(
                    power_balance,  # Available excess power
                    max_charge_rate,  # C-rate limit
                    E_bat * 0.9 - battery_energy[t]  # Space in battery
                )
                
                # Charge the battery
                battery_power[t] = max_charge
                battery_energy[t + 1] = battery_energy[t] + max_charge * eta_ch
                battery_throughput += max_charge
            
            # Discharging logic
            elif power_balance < 0 and battery_soc[t] > 0.2:
                # Determine discharge needed
                discharge_needed = -power_balance
                
                # Limit discharge by battery constraints
                max_discharge = min(
                    discharge_needed,  # Power needed
                    max_discharge_rate,  # C-rate limit
                    battery_energy[t]  # Available energy
                )
                
                # Discharge the battery
                battery_power[t] = -max_discharge
                battery_energy[t + 1] = battery_energy[t] - max_discharge / eta_dch
                battery_throughput += max_discharge
            else:
                # No charging or discharging
                battery_energy[t + 1] = battery_energy[t]
            
            # Update SOC
            battery_soc[t + 1] = battery_energy[t + 1] / E_bat
        
        return {
            'battery_power': battery_power,
            'battery_energy': battery_energy,
            'battery_soc': battery_soc,
            'battery_throughput': battery_throughput
        } 