#!/usr/bin/python3

import sys
import os
import re
import urllib.parse
import urllib.request
import urllib3
import xml.etree.ElementTree as ET
import shutil
import subprocess
from math import ceil

def download_file(base_url, path, output_dir):
    url = urllib.parse.urljoin(base_url, path)
    output_path = os.path.join(output_dir, path)
    if os.path.exists(output_path): return output_path
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"Downloading {url}...")
    http = urllib3.PoolManager()
    resp = http.request('HEAD', url)
    if resp.status!=200: return
    with open(output_path, 'wb') as fp:
        buf = bytearray(64 * 1024)
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'bbb-video-downloader/1.0')
        try:
            resp = urllib.request.urlopen(req)
        except:
            return None
        content_length = resp.headers['Content-Length']
        if content_length is not None: content_length = int(content_length)
        while True:
            with resp:
                n = resp.readinto(buf)
                while n > 0:
                    fp.write(buf[:n])
                    n = resp.readinto(buf)
            current = fp.seek(0, os.SEEK_CUR)
            if content_length is None or current >= content_length:
                break
            print("continuing...")
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'bbb-video-downloader/1.0')
            req.add_header('Range', f'bytes={current}-')
            resp = urllib.request.urlopen(req)
    return output_path

def download(url):
    m = re.match(r'^.*/playback/presentation/2\.0/playback.html\?meetingId=(\S+)$', url)
    if m is None:
        raise f"{url} is not a valid BBB playback URL"
    meeting_id = m.group(1)
    base_url = urllib.parse.urljoin(url, f"/presentation/{meeting_id}/")

    shapes = download_file(base_url, 'shapes.svg', meeting_id)
    doc = ET.parse(shapes)
    for img_url in {img.get('{http://www.w3.org/1999/xlink}href')
        for img in doc.iterfind('.//{http://www.w3.org/2000/svg}image')}:
        download_file(base_url, img_url, meeting_id)

    download_file(base_url, 'panzooms.xml', meeting_id)
    download_file(base_url, 'cursor.xml', meeting_id)
    download_file(base_url, 'deskshare.xml', meeting_id)
    download_file(base_url, 'presentation_text.json', meeting_id)
    download_file(base_url, 'captions.json', meeting_id)
    download_file(base_url, 'slides_new.xml', meeting_id)

    download_file(base_url, 'video/webcams.webm', meeting_id)
    download_file(base_url, 'deskshare/deskshare.webm', meeting_id)
    return meeting_id

def create_slides(input_dir, output_dir, duration, framerate=1):
    doc = ET.parse(os.path.join(input_dir, 'shapes.svg'))
    # if os.path.exists(output_dir):
    #     for f in os.listdir(output_dir):
    #         path = os.path.join(output_dir, f)
    #         if os.path.isdir(path): 
    #              shutil.rmtree(path)
    #         else:
    #             os.remove(path)

    os.makedirs(output_dir, exist_ok=True)
    for img in doc.iterfind('./{http://www.w3.org/2000/svg}image'):
        path = img.get('{http://www.w3.org/1999/xlink}href')
        # If this is a "deskshare" slide, don't show anything
        start = round(float(img.get('in'))*framerate)
        end = round(float(img.get('out'))*framerate)
        if path.endswith('/deskshare.png'):
            create_slides_from_deskshare(os.path.join(input_dir, 'deskshare/deskshare.webm'), output_dir, round(float(img.get('in'))), round(float(img.get('out'))), framerate)
            continue
        print(start, end)

        if start >= duration: continue
        end = min(end, ceil(duration))

        for t in range(start, end):
            shutil.copy(os.path.join(input_dir, path), os.path.join(output_dir, f"image{t}.png"))

def create_slides_from_deskshare(deskshare_filename, slides_dir, start, end, framerate):
    command = f"ffmpeg -ss {start} -i {deskshare_filename} -to {end} -copyts -vf fps={framerate} {slides_dir}/tmp/image%07d.png"
    print(command)
    tmp_dir = os.path.join(slides_dir, 'tmp')
    if os.path.exists(tmp_dir): shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)

    subprocess.run(command, shell=True)
    files = sorted(os.listdir(tmp_dir))

    for k in range(len(files)):
        f = files[k]
        shutil.move(os.path.join(tmp_dir, f), os.path.join(slides_dir, 'image' + str(k + start*framerate)) + '.png')
    shutil.rmtree(tmp_dir)

def create_video(input_dir, output, framerate=1):
    if os.path.exists(output): return
    command = f"ffmpeg -framerate {framerate} -start_number 0 -i '{input_dir}/image%1d.png' -c:v libx264 {output}"
    print(f'Executing... {command}')
    subprocess.run(command, shell=True)

def get_stream_duration(stream_filename):
    command = f"ffprobe -i {stream_filename} -show_format -v quiet | grep duration | sed -n 's/duration=//p'"
    result = subprocess.run(command, shell=True, capture_output=True)
    print(result)
    return float(result.stdout)

def extract_audio(video_filename, audio_filename):
    if os.path.exists(audio_filename): return
    command = f"ffmpeg -i {video_filename} {audio_filename}"
    print(f"executing... {command}")
    subprocess.run(command, shell=True)

def merge_audio_video(audio_filename, video_filename, output_video):
    if os.path.exists(output_video): return
    command = f"ffmpeg -i {audio_filename} -i {video_filename} -c:v copy -c:a aac {output_video}"
    print(f"executing... {command}")
    subprocess.run(command, shell=True)
    
if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 script.py <bbb url>')
        sys.exit(1)

    url = sys.argv[1]
    meeting_id = download(url)
    duration = get_stream_duration(os.path.join(meeting_id, 'video/webcams.webm'))
    print('duration', duration)
    create_slides(meeting_id, os.path.join(meeting_id, 'output-video', 'slides'), duration)
    create_video(os.path.join(meeting_id, 'output-video', 'slides'), os.path.join(meeting_id, 'output-video', 'video-slides.mp4'))
    extract_audio(os.path.join(meeting_id, 'video/webcams.webm'), os.path.join(meeting_id, 'output-video', 'audio.mp3'))
    merge_audio_video(os.path.join(meeting_id, 'output-video', 'audio.mp3'), os.path.join(meeting_id, 'output-video', 'video-slides.mp4'), os.path.join(meeting_id, 'output-video', 'video.mp4'))
