import concurrent.futures
import numpy as np
import argparse
import itertools
import random
from enum import IntEnum
from pathlib import Path


class Status(IntEnum):
    HEALTH = 0
    INFECTED = 1
    RECOVERED = 2
    VACCINATED = -1


def dot_product(a, b):
    return a[0] * b[0] + a[1] * b[1]


class EpidemicDisease(object):
    """ Abstract object for all the epidemic diseases """

    def __init__(
            self, sigma_r: float, sigma_theta: float, conservative_time: int, no_infectious: float,
            gamma: float, r0: float, nc: float, p_daily: float
    ):
        self.sigma_r = sigma_r
        self.sigma_theta = sigma_theta
        self.conservative_time = conservative_time  # Unit: hour
        self.no_infectious = no_infectious
        self.gamma = gamma
        self.r0 = r0
        self.beta_0 = self.gamma * self.r0
        self.nc = nc
        self.p_daily = p_daily
        self.rho_daily = self.nc / (np.pi * 2 ** 2) * self.p_daily
        self.beta_max = self.beta_0 / \
            (self.rho_daily * self.sigma_r ** 2 * self.sigma_theta ** 2)

    def get_progress_time(self, offset: int):
        curr_hour = int(round(offset / 3600))  # the unit of offset is second
        start_infec = curr_hour + self.conservative_time  # hour to be infectious

        p = np.random.uniform(0, 1)
        no_pos_t = int(round(-np.log(p) / (self.gamma * 3600)))
        no_infec_t = int(round(-np.log(p) / (self.no_infectious * 3600)))
        stop_infec = curr_hour + no_infec_t  # hour to be not infectious
        recovery_time = curr_hour + no_pos_t  # hour to recover

        return start_infec, stop_infec, recovery_time  # Unit is hour

    @staticmethod
    def _center(loc):
        cx = (loc[0] + loc[2]) / 2
        cy = (loc[1] + loc[3]) / 2
        return cx, cy

    @staticmethod
    def _dr(loc):
        dx = (loc[0] - loc[2]) / 2
        dy = (loc[1] - loc[3]) / 2
        return dx, dy

    @staticmethod
    def _dis(loc_a, loc_b):
        ds = np.sqrt((loc_a[0] - loc_b[0]) ** 2 + (loc_a[1] - loc_b[1]) ** 2)
        return ds

    def get_angle(self, loc_a, loc_b):
        d_ab = (self._center(loc_b)[0] - self._center(loc_a)[0],
                self._center(loc_b)[1] - self._center(loc_a)[1])
        t_dab = (-d_ab[1], d_ab[0])
        da, db = self._dr(loc_a), self._dr(loc_b)

        dx, dy = dot_product(d_ab, da), dot_product(t_dab, da)
        angle1 = np.arctan2(-dx, dy)

        dx, dy = dot_product(d_ab, db), dot_product(t_dab, db)
        angle2 = np.arctan2(dx, -dy)
        return angle1, angle2

    def get_beta(self, loc_a, loc_b):
        theta1, theta2 = self.get_angle(loc_a, loc_b)
        r = self._dis(self._center(loc_a), self._center(loc_b))
        beta = self.beta_max * np.exp(-(r ** 2 / (2 * self.sigma_r ** 2)) -
                                      (theta1 ** 2 + theta2 ** 2) / (2 * self.sigma_theta ** 2))
        return beta

    def get_transmission_rate(self, t, status_a, status_b, loc_a, loc_b, progress_time_a, progress_time_b):
        curr_hour = int(round(t / 3600))
        if status_a == Status.HEALTH and status_b == Status.INFECTED:
            stop_infec = progress_time_b[1]
            start_infec = progress_time_b[0]
            if stop_infec >= curr_hour >= start_infec:
                b_i, b_j = self.get_beta(loc_a, loc_b), 0
            else:
                b_i, b_j = 0, 0
        elif status_a == Status.INFECTED and status_b == Status.HEALTH:
            stop_infec = progress_time_a[1]
            start_infec = progress_time_a[0]
            if stop_infec >= curr_hour >= start_infec:
                b_i, b_j = 0, self.get_beta(loc_a, loc_b)
            else:
                b_i, b_j = 0, 0
        else:
            b_i, b_j = 0, 0
        return b_i, b_j


class Classroom(object):
    def __init__(
            self, disease: EpidemicDisease, info_path: Path, data_path: Path, output_interval: int,
            max_sim_days: int, half_class: bool, vaccine_efficacy_rate: float, output_root: Path
    ):
        self.disease = disease
        self.teacher_num, self.kid_num = self.load_class_ob_info(info_path)
        self.location_data = self.load_class_ob_data(data_path)
        self.max_simulation_days = max_sim_days
        self.half_class = half_class
        self.vaccine_efficacy_rate = vaccine_efficacy_rate
        self.output_root = output_root
        self.output_interval = output_interval

    @staticmethod
    def load_class_ob_info(info_path: Path):
        with open(str(info_path), 'r') as rf:
            for line in rf:
                pass
            line = line.strip().split(' ')
            teachers, kids = int(float(line[0])), int(float(line[1]))
        return teachers, kids

    @staticmethod
    def load_class_ob_data(data_path: Path):
        data = list()
        location_file = open(str(data_path), 'r')
        for line in location_file:
            line = line.strip().split(',')[1:]
            loc_dict = dict()
            for i in range(0, len(line), 4):
                lft_x, lft_y, rht_x, rht_y = map(float, line[i:i + 4])
                if lft_x != -1 and lft_y != -1 and rht_x != -1 and rht_y != -1:
                    loc_dict[i // 4] = (lft_x, lft_y, rht_x, rht_y)
                else:
                    pass
            data.append(loc_dict)
        return data

    @staticmethod
    def _append_status(output_path: Path, status):
        with open(str(output_path), 'a') as f:
            f.write('{}\n'.format(
                ','.join(str(int(status[sub])) for sub in sorted(status))))

    def kid_indices(self):
        return list(range(self.teacher_num, self.teacher_num + self.kid_num))

    def sub_indices(self):
        return list(range(self.teacher_num + self.kid_num))

    def teacher_indices(self):
        return list(range(self.teacher_num))

    def num_sim_teachers(self):
        return 1 if self.half_class else self.teacher_num

    def num_sim_kids(self):
        return int(self.kid_num / 2 + 0.5) if self.half_class else self.kid_num

    def class_time(self):
        return len(self.location_data)

    def init_status(self, zero_patient_index: int):
        status = {zero_patient_index: Status.INFECTED}
        kids = self.kid_indices()
        kids.remove(zero_patient_index)
        for kid in random.sample(kids, self.num_sim_kids() - 1):
            status[kid] = Status.HEALTH
        for teacher in random.sample(self.teacher_indices(), self.num_sim_teachers()):
            if np.random.uniform(0.0, 1.0) > self.vaccine_efficacy_rate:
                status[teacher] = Status.HEALTH
            else:
                status[teacher] = Status.VACCINATED
        return status

    def simulate_transmission(self, t, status, loc_dict, progress_time):
        sum_beta = {sub: 0 for sub in status}
        for pair in itertools.combinations(status, 2):
            kid_i, kid_j = pair[0], pair[1]
            if kid_i in loc_dict and kid_j in loc_dict:
                beta_i, beta_j = self.disease.get_transmission_rate(
                    t, status[kid_i], status[kid_j],
                    loc_dict[kid_i], loc_dict[kid_j],
                    progress_time[kid_i], progress_time[kid_j]
                )
                sum_beta[kid_i] += beta_i
                sum_beta[kid_j] += beta_j

        for kid in status:
            if status[kid] == Status.HEALTH:
                if np.random.uniform(0.0, 1.0) <= sum_beta[kid]:
                    status[kid] = Status.INFECTED
                    progress_time[kid] = self.disease.get_progress_time(t)

        return status, progress_time

    @staticmethod
    def check_recovery(t, status, progress_time):
        for sub in status:
            if status[sub] == Status.INFECTED and progress_time[sub][2] <= t / 3600:
                status[sub] = Status.RECOVERED
        return status

    def simulate(self, status, out_path: Path):
        """ Simulate the transmission in the classroom based on the given initial condition

        Args:
            status: Initial status of the classroom used in the simulation
            out_path: Path to write the outputs
        """
        t = 0
        progress_time = dict()
        for sub in status:
            progress_time[sub] = self.disease.get_progress_time(t)

        for day in range(1, self.max_simulation_days):
            # Update the status by daily classroom observation
            for loc_dict in self.location_data:
                if t % self.output_interval == 0:
                    status = self.check_recovery(t, status, progress_time)
                    self._append_status(out_path, status)
                    if Status.INFECTED not in status.values():
                        return
                status, progress_time = self.simulate_transmission(
                    t, status, loc_dict, progress_time)
                t += 1

            # Simulate off-class recovery
            if day % 5 == 0:
                delta_t = 3 * 24 * 3600 - self.class_time()
            else:
                delta_t = 24 * 3600 - self.class_time()
            for _ in range(delta_t):
                if t % self.output_interval == 0:
                    status = self.check_recovery(t, status, progress_time)
                    self._append_status(out_path, status)
                    if Status.INFECTED not in status.values():
                        return
                t += 1

    def run_simulation(self, idx):
        zero_patient_index, sim_id = idx
        status = self.init_status(zero_patient_index)
        output_folder = self.output_root / \
            ('half_class' if self.half_class else 'full_class') / \
            'zero_patient_{}'.format(zero_patient_index)
        if not output_folder.exists():
            output_folder.mkdir(parents=True)
        output_path = output_folder / 'simulation{}.csv'.format(sim_id)
        with open(str(output_path), 'w') as f:
            f.write(','.join(str(sub) for sub in sorted(status)))
            f.write('\n')
        print('Start Simulation: Zero Patient {}, Run {}'.format(
            zero_patient_index, sim_id))
        self.simulate(status, output_path)
        print('Finish Simulation: Zero Patient {}, Run {}'.format(
            zero_patient_index, sim_id))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Epidemic Disease Transmission Simulation in the Classroom')
    parser.add_argument('data_path', type=str,
                        help='Path to the data folder of the classroom observation')
    parser.add_argument('num_simulations', type=int,
                        help='Number of simulations per observation per zero patient')
    parser.add_argument('--half_class', action='store_true',
                        help='Determined whether the simulations are based on half or full class setting')
    parser.add_argument('--ob_info', type=str, default='info.dat',
                        help='The relative path to the classroom observation info file')
    parser.add_argument('--ob_data', type=str, default='all_xy.csv',
                        help='The relative path to the classroom observation data file')
    parser.add_argument('--output_root', type=str, default='.',
                        help='The relative path to the root of output folder')
    parser.add_argument('--max_simulation_day', type=int, default=240,
                        help='The maximal number of days for each simulation')
    parser.add_argument('--vaccine_efficacy_rate', type=float, default=0.86,
                        help='The expected probability of vaccine being effective')
    parser.add_argument('--output_interval', type=int, default=3600,
                        help='The time interval in second to output the status in output')
    parser.add_argument('--sigma_r', type=int, default=2,
                        help='The sigma of infectiousness in distance')
    parser.add_argument('--sigma_theta', type=float, default=45 * np.pi / 180,
                        help='The sigma of infectiousness in relative angle')
    parser.add_argument('--conservative_time', type=float, default=24,
                        help='The number of hours before an infected subject becomes infectious')
    parser.add_argument('--no_infectious', type=float, default=1 / (10 * 24 * 3600.0),
                        help='no_infectious of the epidemic disease')
    parser.add_argument('--gamma', type=float, default=1 / (14 * 24 * 3600.0),
                        help='gamma of the epidemic disease')
    parser.add_argument('--r0', type=float, default=2,
                        help='R0 of the epidemic disease')
    parser.add_argument('--nc', type=float, default=10,
                        help='Nc of the epidemic disease')
    parser.add_argument('--p_daily', type=float, default=15 / (24 * 60.0),
                        help='p_daily of the epidemic disease')
    args = parser.parse_args()

    covid = EpidemicDisease(
        args.sigma_r, args.sigma_theta, args.conservative_time, args.no_infectious,
        args.gamma, args.r0, args.nc, args.p_daily
    )
    cls = Classroom(
        covid, Path(args.data_path) / args.ob_info, Path(args.data_path) /
        args.ob_data, args.output_interval,
        args.max_simulation_day, args.half_class, args.vaccine_efficacy_rate, Path(
            args.data_path) / args.output_root
    )
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = executor.map(
            cls.run_simulation,
            itertools.product(cls.kid_indices(), list(
                range(args.num_simulations)))
        )
