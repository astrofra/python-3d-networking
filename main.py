import harfang as hg
import socket
import threading
import pickle
import time
import numpy as np
import cv2
import ctypes

from utils import RangeAdjust
from name_tag import DrawNameTag

# Init socket and server-linked variables
# UDP_IP = "192.168.0.195"
UDP_IP = "127.0.0.1"
UDP_PORT = 5005
SEND_ID = 0
MESSAGE = [0, 0, 0, 0, 0, 0, 0, 0, time.time()]

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def HandleSend():
	global MESSAGE, SEND_ID
	while True:
		sock.sendto(pickle.dumps(MESSAGE), (UDP_IP, UDP_PORT))
		SEND_ID += 1
		time.sleep(1/60)

def HandleReceive(packet: tuple):
	players, old_players, lerped_players, global_time_end, next_players, global_last_packet, time_deltas = packet
	while True:
		data, addr = sock.recvfrom(1024)
		decoded_data = pickle.loads(data)
		if decoded_data[0] == 1:
			if time.time() < global_time_end and global_time_end != 0:
				next_players = decoded_data[1]
				next_players.append(time.time())
				if global_last_packet == 0:
					global_last_packet = time.time()
				else:
					time_deltas.insert(0, time.time() - global_last_packet)
					global_last_packet = time.time()
					if len(time_deltas) > 20:
						time_deltas.pop()
			else:
				if len(players) == len(lerped_players):
					old_players = lerped_players.copy()
				else:
					old_players = players.copy()
				players = decoded_data[1]
				players.append(time.time())
				if global_last_packet == 0:
					global_last_packet = time.time()
				else:
					time_deltas.insert(0, time.time() - global_last_packet)
					global_last_packet = time.time()
					if len(time_deltas) > 20:
						time_deltas.pop()

def InitRenderToTexture(res, frame_buffer_name = "FrameBuffer", pipeline_texture_name = "tex_rb", texture_name = "tex_color_ref", res_x = 512, res_y = 512):
	frame_buffer = hg.CreateFrameBuffer(res_x, res_y, hg.TF_RGBA8, hg.TF_D24, 4, frame_buffer_name)
	color = hg.GetColorTexture(frame_buffer)

	tex_color_ref = res.AddTexture(pipeline_texture_name, color)
	tex_readback = hg.CreateTexture(res_x, res_y, texture_name, hg.TF_ReadBack | hg.TF_BlitDestination, hg.TF_RGBA8)

	picture = hg.Picture(res_x, res_y, hg.PF_RGBA32)

	return frame_buffer, color, tex_color_ref, tex_readback, picture

def GetOpenCvImageFromPicture(picture):
	picture_width, picture_height = picture.GetWidth(), picture.GetHeight()
	picture_data = picture.GetData()
	bytes_per_pixels = 4
	data_size = picture_width * picture_height * bytes_per_pixels
	buffer = (ctypes.c_char * data_size).from_address(picture_data)
	raw_data = bytes(buffer)
	np_array = np.frombuffer(raw_data, dtype=np.uint8)
	image_rgba = np_array.reshape((picture_height, picture_width, bytes_per_pixels))
	image_bgr = cv2.cvtColor(image_rgba, cv2.COLOR_BGR2RGB)

	return image_bgr


def main():
	players = []
	lerped_players = players
	old_players = players
	next_players = players
	players_spawned = 0
	players_instances = []
	global_time_end = 0
	global_last_packet = 0
	time_deltas = [0.1]

	arguments = players, old_players, lerped_players, global_time_end, next_players, global_last_packet, time_deltas

	threading.Thread(target=HandleSend).start()
	threading.Thread(target=HandleReceive, args=[arguments]).start()

	# Init Harfang
	hg.InputInit()
	hg.WindowSystemInit()

	res_x, res_y = 1280, 720

	win = hg.NewWindow('3D Server - Client Scene', res_x, res_y)
	hg.RenderInit(win)

	pipeline = hg.CreateForwardPipeline()
	res = hg.PipelineResources()

	hg.AddAssetsFolder("server_client_demo_compiled")
	hg.ImGuiInit(10, hg.LoadProgramFromAssets('core/shader/imgui'), hg.LoadProgramFromAssets('core/shader/imgui_image'))
	line_shader = hg.LoadProgramFromAssets('core/shader/white')
	name_shader = hg.LoadProgramFromAssets('core/shader/grey')
	font = hg.LoadFontFromAssets('font/ticketing.ttf', 96)
	font_prg = hg.LoadProgramFromAssets('core/shader/font')
	text_uniform_values = [hg.MakeUniformSetValue('u_color', hg.Vec4(1, 1, 1))]
	text_render_state = hg.ComputeRenderState(hg.BM_Alpha, hg.DT_Always, hg.FC_Disabled)

	vtx_layout = hg.VertexLayout()
	vtx_layout.Begin()
	vtx_layout.Add(hg.A_Position, 3, hg.AT_Float)
	vtx_layout.End()

	# load scene
	scene = hg.Scene()
	hg.LoadSceneFromAssets("level_1_full.scn", scene, res, hg.GetForwardPipelineInfo())
	cam = scene.GetNode('Camera')
	cam_rot = scene.GetNode('camrotation')

	# AAA pipeline
	pipeline_aaa_config = hg.ForwardPipelineAAAConfig()
	pipeline_aaa = hg.CreateForwardPipelineAAAFromAssets("core", pipeline_aaa_config, hg.BR_Equal, hg.BR_Equal)
	pipeline_aaa_config.sample_count = 1
	pipeline_aaa_config.motion_blur = 0


	# input devices and fps controller states
	keyboard = hg.Keyboard()
	mouse = hg.Mouse()

	# main loop
	frame = 0
	state = "none"
	show_lerp = True
	show_pred = True
	show_real = True
	auto_move = False
	vid_scene_opaque = 0
	vtx_2 = hg.Vertices(vtx_layout, 2)
	vtx_4 = hg.Vertices(vtx_layout, 4)


	cam = scene.GetNode("Camera")
	trs = scene.GetNode("red_player")
	z_near = cam.GetCamera().GetZNear()
	z_far = cam.GetCamera().GetZFar()
	fov = cam.GetCamera().GetFov()

	camera_world_transform = hg.TransformationMat4(hg.Vec3(2,1,0), hg.Vec3(0,0,0))
	camera_robot = hg.CreateCamera(scene, camera_world_transform, z_near, z_far, fov)
	camera_robot.GetTransform().SetParent(trs)

	frame_buffer, color, tex_color_ref, tex_readback, picture = InitRenderToTexture(res)

	while not hg.ReadKeyboard().Key(hg.K_Escape) and hg.IsWindowOpen(win): #and hg.IsWindowOpen(win_robot_view):
		render_was_reset, res_x, res_y = hg.RenderResetToWindow(win, res_x, res_y, hg.RF_VSync)
		keyboard.Update()
		mouse.Update()
		dt = hg.TickClock()

		vid = 0
		pass_ids = 0

		min_node_pos = scene.GetNode('area_min').GetTransform().GetPos()
		max_node_pos = scene.GetNode('area_max').GetTransform().GetPos()
		min_x = min_node_pos.x
		min_z = min_node_pos.z
		max_x = max_node_pos.x
		max_z = max_node_pos.z

		if len(players) - 1 > players_spawned:
			player_node, _  = hg.CreateInstanceFromAssets(scene, hg.TransformationMat4(hg.Vec3(players[players_spawned][0], players[players_spawned][1], players[players_spawned][2]), hg.Vec3(players[players_spawned][3], players[players_spawned][4], players[players_spawned][5])), "objects_library/players/yellow_robot.scn", res, hg.GetForwardPipelineInfo())
			player_lerp_node, _  = hg.CreateInstanceFromAssets(scene, hg.TransformationMat4(hg.Vec3(players[players_spawned][0], players[players_spawned][1], players[players_spawned][2]), hg.Vec3(players[players_spawned][3], players[players_spawned][4], players[players_spawned][5])), "objects_library/players/ghost_uninterpolated_robot.scn", res, hg.GetForwardPipelineInfo())
			player_pred_node, _  = hg.CreateInstanceFromAssets(scene, hg.TransformationMat4(hg.Vec3(players[players_spawned][0], players[players_spawned][1], players[players_spawned][2]), hg.Vec3(players[players_spawned][3], players[players_spawned][4], players[players_spawned][5])), "objects_library/players/ghost_predict_robot.scn", res, hg.GetForwardPipelineInfo())

			players_instances.append([[player_node, player_lerp_node, player_pred_node], players_spawned])
			players_spawned += 1
			print("Spawned a new player")

		new_lerped_players = []

		try:
			for pinstance in players_instances:
				if len(old_players) == len(players):
					player_transform = pinstance[0][0].GetTransform()
					player_nolerp_transform = pinstance[0][1].GetTransform()
					player_pred_transform = pinstance[0][2].GetTransform()
					player_id = pinstance[1]
					player_updated_pos = hg.Vec3(players[player_id][0], players[player_id][1], players[player_id][2])
					player_updated_rot = hg.Vec3(players[player_id][3], players[player_id][4], players[player_id][5])
					player_old_pos = hg.Vec3(old_players[player_id][0], old_players[player_id][1], old_players[player_id][2])
					player_old_rot = hg.Vec3(old_players[player_id][3], old_players[player_id][4], old_players[player_id][5])
					updated_time = players[-1]
					time_delta = sum(time_deltas) / len(time_deltas)
					time_end = updated_time + time_delta
					global_time_end = time_end
					adjusted_time = RangeAdjust(time.time(), updated_time, time_end, 0, 1)
					wanted_pos = hg.Lerp(player_old_pos, player_updated_pos, adjusted_time)
					wanted_rot = hg.Lerp(player_old_rot, player_updated_rot, adjusted_time)

					if time.time() > time_end and len(next_players) > 0:
						if next_players[-1] > updated_time:
							old_players = players.copy()
							next_players[-1] = time.time()
							players = next_players.copy()
							player_updated_pos = hg.Vec3(players[player_id][0], players[player_id][1], players[player_id][2])
							player_updated_rot = hg.Vec3(players[player_id][3], players[player_id][4], players[player_id][5])
							current_pos = player_transform.GetPos()
							current_rot = player_transform.GetRot()
							old_players[player_id][0] = current_pos.x
							old_players[player_id][1] = current_pos.y
							old_players[player_id][2] = current_pos.z
							old_players[player_id][3] = current_rot.x
							old_players[player_id][4] = current_rot.y
							old_players[player_id][5] = current_rot.z
							player_old_pos = hg.Vec3(old_players[player_id][0], old_players[player_id][1], old_players[player_id][2])
							player_old_rot = hg.Vec3(old_players[player_id][3], old_players[player_id][4], old_players[player_id][5])
							updated_time = players[-1]
							old_time = old_players[-1]

							time_delta = sum(time_deltas) / len(time_deltas)
							time_end = updated_time + time_delta
							global_time_end = time_end
							adjusted_time = RangeAdjust(time.time(), updated_time, time_end, 0, 1)
							wanted_pos = hg.Lerp(player_old_pos, player_updated_pos, adjusted_time)
							wanted_rot = hg.Lerp(player_old_rot, player_updated_rot, adjusted_time)

					new_lerped_players.append([wanted_pos.x, wanted_pos.z, wanted_rot.x, wanted_rot.y, wanted_rot.z])
					DrawNameTag(vtx_2, vtx_4, wanted_pos, line_shader, name_shader, vid_scene_opaque, "Remote " + str(pinstance[1] + 1), font, font_prg, text_uniform_values, text_render_state, cam.GetTransform().GetWorld())
					if show_lerp:
						player_transform.SetPos(wanted_pos)
						player_transform.SetRot(wanted_rot)
					else:
						player_transform.SetPos(hg.Vec3(-100, -100, -100))
					# prediction
					pos_dif = player_updated_pos - player_old_pos
					predicted_pos = player_updated_pos + (pos_dif * adjusted_time)
					rot_dif = player_updated_rot - player_old_rot
					predicted_rot = player_updated_rot + (rot_dif * adjusted_time)
					if show_pred and predicted_pos.x < max_x and predicted_pos.x > min_x and predicted_pos.z < max_z and predicted_pos.z > min_z:
						player_pred_transform.SetPos(predicted_pos)
						player_pred_transform.SetRot(predicted_rot)
					elif not show_pred:
						player_pred_transform.SetPos(hg.Vec3(-100, -100, -100))

					if show_real:
						player_nolerp_transform.SetPos(hg.Vec3(players[player_id][0], players[player_id][1], players[player_id][2]))
						player_nolerp_transform.SetRot(hg.Vec3(players[player_id][3], players[player_id][4], players[player_id][5]))
					else:
						player_nolerp_transform.SetPos(hg.Vec3(-100, -100, -100))

		except Exception as err:
			print(err)

		lerped_players = new_lerped_players

		trs = scene.GetNode('red_player').GetTransform()
		pos = trs.GetPos()
		rot = trs.GetRot()

		MESSAGE = [0, pos.x, pos.y, pos.z, rot.x, rot.y, rot.z, SEND_ID, time.time()]
		world = hg.RotationMat3(rot.x, rot.y, rot.z)
		front = hg.GetZ(world)

		simulated_pos_forward = pos + front * (hg.time_to_sec_f(dt) * 10)
		simulated_pos_backward = pos - front * (hg.time_to_sec_f(dt) * 10)
		if (keyboard.Down(hg.K_Up) or auto_move) and simulated_pos_forward.x < max_x and simulated_pos_forward.x > min_x and simulated_pos_forward.z < max_z and simulated_pos_forward.z > min_z:
			trs.SetPos(pos + front * (hg.time_to_sec_f(dt) * 10))
		if keyboard.Down(hg.K_Down) and simulated_pos_backward.x < max_x and simulated_pos_backward.x > min_x and simulated_pos_backward.z < max_z and simulated_pos_backward.z > min_z:
			trs.SetPos(pos - front * (hg.time_to_sec_f(dt) * 10))
		if keyboard.Down(hg.K_Right) or auto_move:
			trs.SetRot(hg.Vec3(rot.x, rot.y + (hg.time_to_sec_f(dt)), rot.z))
		if keyboard.Down(hg.K_Left):
			trs.SetRot(hg.Vec3(rot.x, rot.y - (hg.time_to_sec_f(dt)), rot.z))

		scene.Update(dt)

		scene.SetCurrentCamera(cam)
		vid, pass_ids = hg.SubmitSceneToPipeline(vid, scene, hg.IntRect(0, 0, res_x, res_y), True, pipeline, res, pipeline_aaa, pipeline_aaa_config, frame)
		scene.SetCurrentCamera(camera_robot)
		vid, pass_ids = hg.SubmitSceneToPipeline(vid, scene, hg.IntRect(0, 0, res_x, res_y), True, pipeline, res, frame_buffer.handle)


		vid_scene_opaque = hg.GetSceneForwardPipelinePassViewId(pass_ids, hg.SFPP_Opaque)

		DrawNameTag(vtx_2, vtx_4, pos, line_shader, name_shader, vid_scene_opaque, "Local", font, font_prg, text_uniform_values, text_render_state, cam.GetTransform().GetWorld())

		hg.ImGuiBeginFrame(res_x, res_y, dt, mouse.GetState(), keyboard.GetState())

		hg.ImGuiSetNextWindowPos(hg.Vec2(10, 10))
		hg.ImGuiSetNextWindowSize(hg.Vec2(300, 180), hg.ImGuiCond_Once)

		if hg.ImGuiBegin('Online Robots Config'):
			was_changed_lerp, show_lerp = hg.ImGuiCheckbox('Show Linear Interpolation', show_lerp)
			was_changed_pred, show_pred = hg.ImGuiCheckbox('Show Prediction', show_pred)
			was_changed_real, show_real = hg.ImGuiCheckbox('Show Real Position', show_real)
			was_changed_move, auto_move = hg.ImGuiCheckbox('Automatic Robot Movement', auto_move)

		hg.ImGuiEnd()

		if hg.ImGuiBegin("Render Robot View"):
			imgui_robot_view = hg.ImGuiImage(color, hg.Vec2(512, 512))
		hg.ImGuiEnd()


		if (hg.ReadKeyboard().Key(hg.K_Space)):
			if state == "none":
				state = "capture"
				frame_count_capture, vid = hg.CaptureTexture(vid, res, tex_color_ref, tex_readback, picture)
			elif state == "capture" and frame_count_capture <= frame:
				image = GetOpenCvImageFromPicture(picture)
				if image is not None:
					cv2.imshow("Image", image)
					state = "none"

		hg.ImGuiEndFrame(255)
		frame = hg.Frame()

		hg.UpdateWindow(win)

	cv2.waitKey(0)
	cv2.destroyAllWindows()
	hg.RenderShutdown()
	hg.DestroyWindow(win)

main()