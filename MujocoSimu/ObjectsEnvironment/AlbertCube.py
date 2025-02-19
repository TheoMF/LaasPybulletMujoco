import math
from Enums import ObjectType,MoveType,JumpType,TurnType
import numpy as np
from MujocoSimu.ObjetsEnvironnement.Cube import Cube
import mujoco as mj
from scipy.spatial.transform import Rotation

# Actor's class
class AlbertCube(Cube):

    def __init__(self, room_manager, data, model):
        self.actual_room = 0                   # actual level with which the actor is interacting
        self.room_manager = room_manager       # class in which all levels are contained in a list
        self.data = data                       # mujoco's data struct
        self.model = model                     # mujoco's model struct
        self.id = self.model.body("Albert").id
        self.geom = self.model.body(self.id).geomadr[0]

        # state space ( Albert doesn't have it's acces )
        self.memory_state = []                        # stacking the last 5 states
        self.current_state = self.get_current_state()


        # observation space ( Albert has it's acces )
        self.memory_observation = []  # stacking the last 5 observations

        # features necessary for movements
        self.x_jumping_factor = 0
        self.start_jumping = False
        self.jump_orientation = 0

    def has_fallen(self):
        pos = self.data.xpos[self.id]
        return pos[2] < self.room_manager.room_array[self.actual_room].global_coord[2]

    def reset_position_orientation(self, pos, ori_euler):
        ori_quaternion = quaternion_from_euler(ori_euler)
        room_coord = self.room_manager.room_array[self.actual_room].global_coord
        new_pos = [pos[0] + room_coord[0], pos[1] + room_coord[1], pos[2] + room_coord[2]]
        self.data.qpos[0:3] = new_pos
        self.data.qpos[3:7] = ori_quaternion


    def raycasting(self, viewer):
        cube_pos = self.data.xpos[self.id]
        cube_ori = self.data.xquat[self.id]
        ray_vects=grid_vision(cube_pos,cube_ori,ray_length=10)

        contact_results = []
        geom_ids = np.empty([21])
        geom_id = np.array([130], dtype='int32')
        for n in range(21):
            contact_results.append(
                mj.mj_ray(self.model, self.data, pnt=cube_pos, vec=ray_vects[n], geomgroup=None, flg_static=1,
                          bodyexclude=131,
                          geomid=geom_id)) # raycasting function
            geom_ids[n] = geom_id


        body_types = [] # types of detected objects
        for n in range(21):
            if geom_ids[n] > 0:  # we don't take into account -1 ( empty ) and 0 ( plane ) ids
                body_types.append(self.check_type(self.model.geom(int(geom_ids[n])).bodyid[0],
                                                self.room_manager.room_array[self.actual_room]))
            else:
                body_types.append(0)

        obs = []
        for n in range(21):
            obs.append([body_types[n], contact_results[n]])

        show_grid(viewer,cube_pos,ray_vects) # if visible rays are needed

        return obs

    def jump(self, jump, move):
        i = 13000  # force du jump sur un pas
        move_x = 0
        if move == MoveType.BACKWARD_MOVE.value:
            move_x = -1
        elif move == MoveType.FORWARD_MOVE.value:
            move_x = 1
        if jump == JumpType.JUMP.value:
            if self.in_contact_with_floor_or_button():
                self.start_jumping = True
        if self.start_jumping:
            #application d'une impulsion pour un saut dans le cas où albert est sur le sol ou un boutton
            self.x_jumping_factor = move_x
            self.jump_orientation = euler_from_quaternion(self.data.xquat[self.id])[2]
            impulse = np.concatenate((np.array([5 * self.x_jumping_factor, 0, i]), np.array([0, 0, 0])))
            self.data.xfrc_applied[self.id] = impulse
            self.start_jumping = False

    def yaw_turn(self, rotate): # fonction de rotation d'albert
        move_z = 0
        print("rotate : "+str(rotate))
        if rotate == TurnType.LEFT_TURN.value:
            move_z = -1
        elif rotate == TurnType.RIGHT_TURN.value:
            move_z = 1
        angular_velocity = [0, 0, 2 * move_z]  # mz=1/0/-1
        print("angular velocity : "+str(angular_velocity))
        self.data.qvel[3:6] = angular_velocity


    def move(self, move):  # fonction définissant les mouvements sur le sol
        move_x = 0
        if move == MoveType.BACKWARD_MOVE.value:
            move_x = -1
        elif move == MoveType.FORWARD_MOVE.value:
            move_x = 1
        linear_velocity = [move_x * 300, 0, 0]
        ori = self.data.xquat[self.id]
        euler = euler_from_quaternion(ori)
        mat = euler_to_rotation_matrix(euler)
        linear_velocity = np.dot(mat, linear_velocity)
        if (self.in_contact_with_floor_or_button()):
            impulse = np.concatenate((np.array(linear_velocity), np.array([0, 0, 0])))
            self.data.xfrc_applied[self.id] = impulse

    def take_action(self, action):  # 1: rotate, 2 : move, 3 : jump # fonction de traitement de l'action à effectuer

        rotate = action[0]
        move = action[1]
        jump = action[2]
        self.yaw_turn(rotate)
        self.move(move)
        self.jump(jump, move)
        self.current_state = self.get_current_state()


    def get_observation(self, viewer): # fonction retournant l'observation d'albert actualisé
        contact_results = self.raycasting(viewer)
        current_observation = np.empty(42)
        for i in range(len(contact_results)):
            room = self.room_manager.room_array[self.actual_room]
            if contact_results[i][0] == 0 or contact_results[i][0] == -1:
                current_observation[21 + i] = 10  # à changer en la distance du rayon
                current_observation[i] = ObjectType.NONE.value
            else:
                type = contact_results[i][0]
                distance = contact_results[i][1]
                current_observation[21 + i] = distance
                current_observation[i] = type

        self.add_to_memory_observation(current_observation)
        observation = self.flat_memory()
        return observation

    def check_type(self, id, room): # retourne à quel type d'objet l'id fait référence
        buttons = room.buttons_array.keys()
        if id in buttons:
            return ObjectType.BUTTON.value

        if id in room.floor_array:
            return ObjectType.FLOOR.value

        if id in room.wall_array:
            return ObjectType.WALL.value

        fences = room.fences_array
        if id in fences:
            return ObjectType.FENCE.value

        iblocks = room.iblocks_array
        if id in iblocks:
            return ObjectType.IBLOCK.value
        if id == room.door_array[0]:
            if room.door_array[1].is_opened: # si porte ouverte : considérée comme un boutton
                return ObjectType.BUTTON.value
            return ObjectType.WALL.value # sinon considérée comme un mur
        return ObjectType.NONE.value



    def add_to_memory_observation(self, current_observation):  # ajout de l'observation courante à la liste des 5 dernieres observations
        if len(self.memory_observation) < 5:
            self.memory_observation.append(current_observation)
        else:
            self.memory_observation[0] = self.memory_observation[1]
            self.memory_observation[1] = self.memory_observation[2]
            self.memory_observation[2] = self.memory_observation[3]
            self.memory_observation[3] = self.memory_observation[4]
            self.memory_observation[4] = current_observation

    def add_to_memory_state(self, current_state): # ajout de l'état courant du système à la liste des 5 derniers états
        if len(self.memory_state) < 5:
            self.memory_state.append(current_state)
        else:
            self.memory_state[0] = self.memory_state[1].copy()
            self.memory_state[1] = self.memory_state[2].copy()
            self.memory_state[2] = self.memory_state[3].copy()
            self.memory_state[3] = self.memory_state[4].copy()
            self.memory_state[4] = current_state.copy()

    def get_previous_state(self):
        if (len(self.memory_state) <= 1):
            return None
        return self.memory_state[len(self.memory_state) - 2]

    def get_current_state(self): # fonction actualisant l'état courant du système et retournant les 5 derniers états
        room = self.room_manager.room_array[self.actual_room]
        current_state = {}
        pos_albert = self.data.xpos[self.id]
        buttons = room.buttons_array.values()
        buttons = binarize_button_states(buttons)
        door = np.prod(buttons)
        door_pos = self.data.xpos[room.door_array[0]]

        current_state["CharacterPosition"] = [pos_albert[0], pos_albert[1], pos_albert[2]]
        current_state["doorState"] = door
        current_state["doorPosition"] = [door_pos[0], door_pos[1]]

        current_state["buttonsState"] = [buttons[i] for i in range(len(buttons))]

        # add contactpoints
        contact_points = self.get_contact_points()

        if len(contact_points) == 0:
            current_state["contactPoints"] = [0, 0, 0, 0, 0, 0]
        else:
            contact_types = []
            ids = []
            for i in range(len(contact_points)):
                id = contact_points[i][0]

                type = self.check_type(id, self.room_manager.room_array[
                    self.actual_room])
                if id not in ids:
                    contact_types.append(type)
                    ids.append(id)
                if type == ObjectType.BUTTON.value:
                    if id == self.room_manager.room_array[self.actual_room].door_array[0]:
                        if self.room_manager.room_array[self.actual_room].door_array[1].is_opened:
                            continue
                    pushed_button = self.room_manager.room_array[0].buttons_array.get(id)
                    if (pushed_button.is_pressed == False):
                        pushed_button.got_pressed(self.model)
            while (len(contact_types) < 6):
                contact_types.append(ObjectType.NONE.value)
            current_state["contactPoints"] = contact_types

        self.room_manager.room_array[self.actual_room].check_buttons_pushed(self.model)

        self.add_to_memory_state(current_state)

        return current_state

    def flat_memory(self): # met l'observation dans le bon format nécessaire à l'entrainement
        obs = np.zeros(735)
        for i in range(len(self.memory_observation)):
            for j in range(42):
                if j < 21:
                    #print("aaaa : "+str(self.memory_observation[i][j]))
                    obs[i * 21*6 + j*6:i * 21*6 + (j+1)*6] = self.binarize_type(int(self.memory_observation[i][j])) # type storage
                else:
                    #print("bbbbb ; " +str(self.memory_observation[i][j]))
                    obs[630 + i * 21 + (j - 21)] = self.memory_observation[i][j]
        return obs

    def get_contact_points(self): # retourne les identifiants des objets en contact avec albert
    ################## FONCTION JUSTE DANS MUJOCO
        n = len(self.data.contact.geom1)
        contact_points = []
        for i in range(n):
            g1 = self.data.contact.geom1[i]
            g2 = self.data.contact.geom2[i]
            if self.model.geom(g1).bodyid == self.id or self.model.geom(g2).bodyid == self.id:
                if self.model.geom(g1).bodyid == self.id:
                    body_id = self.model.geom(g2).bodyid
                    contact_points.append(body_id)
                else:
                    body_id = self.model.geom(g1).bodyid
                    contact_points.append(body_id)
        return contact_points

    def in_contact_with_floor_or_button(self): ############## FONCTION JUSTE MUJOCO MAIS TRANSPOSABLE A PYBULLET
        contact_points = self.get_contact_points()
        n = len(contact_points)
        if n == 0:
            return False
        for i in range(n):
            a = self.check_type(contact_points[i][0], self.room_manager.room_array[self.actual_room])

            if a == ObjectType.FLOOR.value or a == ObjectType.BUTTON.value:
                return True
        return False

    def binarize_type(self,type):######### JUSTE DANS MUJOCO
        type_bin=np.zeros((6,))
        type_bin[type]=1
        return type_bin

def binarize_button_states(buttons): # retourne une liste d'états des bouttons ( 1 si le boutton à été appuyé dessus, 0 sinon )
    list = []
    for button in buttons:
        if button.is_pressed:
            list.append(1)
        else:
            list.append(0)
    return list


def euler_to_rotation_matrix(euler):
    # Convert Euler angles to rotation matrix
    # R = Rz(yaw) * Ry(pitch) * Rx(roll)
    roll = euler[0]
    pitch = euler[1]
    yaw = euler[2]
    cos_r, sin_r = np.cos(roll), np.sin(roll)
    cos_p, sin_p = np.cos(pitch), np.sin(pitch)
    cos_y, sin_y = np.cos(yaw), np.sin(yaw)

    rotation_matrix = np.array([
        [cos_y * cos_p, cos_y * sin_p * sin_r - sin_y * cos_r, cos_y * sin_p * cos_r + sin_y * sin_r],
        [sin_y * cos_p, sin_y * sin_p * sin_r + cos_y * cos_r, sin_y * sin_p * cos_r - cos_y * sin_r],
        [-sin_p, cos_p * sin_r, cos_p * cos_r]
    ])

    return rotation_matrix


def euler_from_quaternion(q):
    # Extract quaternion components
    w, x, y, z = q

    # Calculate Euler angles
    # Roll (rotation around x-axis)
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    # Pitch (rotation around y-axis)
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)  # Use 90 degrees if out of range
    else:
        pitch = math.asin(sinp)

    # Yaw (rotation around z-axis)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    # Return Euler radian angles as a vector
    return [roll, pitch, yaw]


def quaternion_from_euler(euler):
    eu = Rotation.from_euler('zyx', euler, degrees=False)
    quat = eu.as_quat()
    return quat

def grid_vision(character_pos,character_ori,ray_length): #retourne la position du bout des tous les rayons nécessaires à la vision
    cube_ori = euler_from_quaternion(character_ori)
    matrice_ori = euler_to_rotation_matrix(cube_ori)


    # On détermine ici les angles des rayons pour le quadrillage
    # départ des angles :
    dep_angles_yaw = -35 * np.pi / 180
    dep_angles_pitch = -12 * np.pi / 180
    # Pas yaw pour 70°
    step_yaw = 70 / 6
    step_yaw_rad = step_yaw * np.pi / 180

    # pas pitch pour 15°
    step_pitch = 15 / 2
    step_pitch_rad = step_pitch * np.pi / 180

    # rayVec1 : premier rayon droit devant le cube
    ray_vects = []
    for i in range(3):
        for n in range(7):
            base_ray = [np.cos((n * step_yaw_rad + dep_angles_yaw)) * np.cos((i * step_pitch_rad + dep_angles_pitch)),
                        np.sin((n * step_yaw_rad + dep_angles_yaw)), np.sin((i * step_pitch_rad + dep_angles_pitch))]
            norm_ray = np.linalg.norm(base_ray)

            a = np.dot(matrice_ori, np.array(
                [(base_ray[0] / norm_ray * ray_length),
                 (ray_length * base_ray[1] / norm_ray),
                 (ray_length * base_ray[2] / norm_ray)
                 ]
            ))

            a[0] += character_pos[0]

            a[1] += character_pos[1]
            a[2] += character_pos[2]

            ray_vects.append(a)
    return ray_vects

def show_grid(viewer,cube_pos,ray_vects): # affiche le raycasting de manière visible
  for n in range(21):
             # if contact_results[n] != -1:
             mj.mjv_initGeom(viewer.scn.geoms[n],
                                 mj.mjtGeom.mjGEOM_LINE, np.zeros(3),
                                 np.zeros(3), np.zeros(9), rgba=np.array([1., 0., 0., 1.], dtype=np.float32))
             mj.mjv_makeConnector(viewer.scn.geoms[n], mj.mjtGeom.mjGEOM_LINE, width=5, a0=cube_pos[0],
                                      a1=cube_pos[1], a2=cube_pos[2], b0=ray_vects[n][0], b1=ray_vects[n][1],
                                      b2=ray_vects[n][2])
