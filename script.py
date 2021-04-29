#!/usr/bin/python3

import sys
import os
import re
import errno
import datetime
import urllib.parse
import urllib.request
import urllib.error
import urllib3
import xml.etree.ElementTree as ET
import shutil
import subprocess
from math import ceil


def download_file(base_url, path, output_dir):
    url = urllib.parse.urljoin(base_url, path)
    output_path = os.path.join(output_dir, path)
    if os.path.exists(output_path):
        return output_path
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    http = urllib3.PoolManager()
    resp = http.request('HEAD', url)
    if resp.status != 200:
        return False
    print(f"Downloading {url}...")
    with open(output_path, 'wb') as fp:
        buf = bytearray(64 * 1024)
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'bbb-video-downloader/1.0')
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.HTTPError:
            return None
        content_length = resp.headers['Content-Length']
        if content_length is not None:
            content_length = int(content_length)
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
        raise Exception(f"{url} is not a valid BBB playback URL")
    meeting_id = m.group(1)
    base_url = urllib.parse.urljoin(url, f"/presentation/{meeting_id}/")

    download_file(base_url, 'metadata.xml', meeting_id)
    shapes = download_file(base_url, 'shapes.svg', meeting_id)

    doc = ET.parse(shapes)
    for img_url in {img.get('{http://www.w3.org/1999/xlink}href')
                    for img in doc.iterfind('.//{http://www.w3.org/2000/svg}image')}:
        download_file(base_url, img_url, meeting_id)

    download_file(base_url, 'panzooms.xml', meeting_id)
    download_file(base_url, 'cursor.xml', meeting_id)
    download_file(base_url, 'deskshare.xml', meeting_id)
    download_file(base_url, 'captions.json', meeting_id)
    download_file(base_url, 'presentation_text.json', meeting_id)
    download_file(base_url, 'slides_new.xml', meeting_id)

    if not download_file(base_url, 'video/webcams.mp4', meeting_id):
        if download_file(base_url, 'video/webcams.webm', meeting_id):
            input_file = os.path.join(meeting_id, 'video/webcams.webm')
            output_file = os.path.join(meeting_id, 'video/webcams.mp4')
            command = f"ffmpeg.exe -i {input_file} -c:a aac -c:v libx264 -crf 0 \
            -preset ultrafast \
            -v quiet -stats {output_file}"
            print(f'Executing... {command}')
            subprocess.run(command, shell=True)

    if not download_file(base_url, 'deskshare/deskshare.mp4', meeting_id):
        if download_file(base_url, 'deskshare/deskshare.webm', meeting_id):
            input_file = os.path.join(meeting_id, 'deskshare/deskshare.webm')
            output_file = os.path.join(meeting_id, 'deskshare/deskshare.mp4')
            command = f"ffmpeg.exe -i {input_file} -c:a aac -c:v libx264 -crf 0 \
            -preset ultrafast \
            -v quiet -stats {output_file}"
            print(f'Executing... {command}')
            subprocess.run(command, shell=True)

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
        imageId = img.get('id')
        # If this is a "deskshare" slide, don't show anything
        start = round(float(img.get('in')) * framerate)
        end = round(float(img.get('out')) * framerate)
        duration = round(duration * framerate)
        if path.endswith('/deskshare.png'):
            print(f"Processing Deskshare {imageId}: {start} -> {end}")
            create_slides_from_deskshare(os.path.join(input_dir, 'deskshare/deskshare.mp4'),
                                         os.path.join(output_dir, f"{imageId}.mp4"), round(float(img.get('in'))),
                                         round(float(img.get('out'))))
            continue
        print(f"Processing {imageId}: {start} -> {end}")

        if start >= duration:
            continue
        end = min(end, ceil(duration))
        output_file = os.path.join(output_dir, f"{imageId}.mp4")
        if os.path.exists(output_file):
            continue

        tmp_dir = os.path.join(output_dir, 'tmp')
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir, exist_ok=True)

        for t in range(start, end):
            shutil.copy(os.path.join(input_dir, path), os.path.join(output_dir, 'tmp', f"image{t}.png"))

        if os.path.exists(output_file):
            os.remove(output_file)
        create_video(tmp_dir, start, output_file, framerate)
        shutil.rmtree(tmp_dir)


def create_slides_from_deskshare(deskshare_file, output_file, start, end):
    delta = round(end - start)
    command = f"ffmpeg -ss {start}s -i {deskshare_file} -t {delta}s \
    -vf scale=\"1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2\" \
    -preset ultrafast \
    -v quiet -stats \
    {output_file}"
    print(f'Executing... {command}')
    subprocess.run(command, shell=True)


def create_video(input_dir, start_number, output_file, framerate=1):
    if os.path.exists(output_file):
        return
    command = f"ffmpeg -framerate {framerate} -start_number {start_number} -i '{input_dir}/image%1d.png' \
    -c:v libx264 \
    -pix_fmt yuv420p \
    -vf scale=\"1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2\" \
    -preset ultrafast \
    -v quiet -stats \
    {output_file}"
    print(f'Executing... {command}')
    subprocess.run(command, shell=True)


def concat_video(input_dir, output_file):
    if os.path.exists(output_file):
        return
    tmp_dir = os.path.join(input_dir, 'tmp')
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    dirFiles = os.listdir(input_dir)
    dirFiles.sort()
    files = sorted(dirFiles, key=extract_number)

    input_file = os.path.join(input_dir, 'tmp', 'files.txt')
    os.makedirs(tmp_dir, exist_ok=True)

    with open(input_file, 'w', encoding='utf-8') as f_out:
        for k in range(len(files)):
            f_out.write(f"file '../{files[k]}'\n")

    command = f"ffmpeg -f concat -safe 0 -i {input_file} -c copy \
    -preset ultrafast \
    -v quiet -stats \
    {output_file}"
    print(f'Executing... {command}')

    subprocess.run(command, shell=True)
    shutil.rmtree(tmp_dir)


def extract_audio(video_file, audio_file, duration):
    if os.path.exists(audio_file):
        return
    command = f"ffmpeg -ss 0s -i {video_file} -t {duration}s -vn -c:a copy \
    -preset ultrafast \
    -v quiet -stats \
    {audio_file}"
    print(f"executing... {command}")
    subprocess.run(command, shell=True)


def generate_overlay(webcams_file, overlay_file, duration):
    if os.path.exists(overlay_file):
        return
    command = f"ffmpeg.exe -i {webcams_file} -t {duration}s -s 320x240 -an \
    -preset ultrafast \
    -v quiet -stats \
    {overlay_file}"
    print(f"executing... {command}")
    subprocess.run(command, shell=True)


def merge_audio_video(audio_file, video_file, output_file, duration):
    if os.path.exists(output_file):
        return
    command = f"ffmpeg -i {audio_file} -i {video_file} -t {duration}s \
    -c:v copy -c:a aac \
    -preset ultrafast \
    -v quiet -stats \
    {output_file}"
    print(f"executing... {command}")
    subprocess.run(command, shell=True)


def merge_video_audio_overlay(video_file, audio_file, overlay_file, output_video, duration):
    if os.path.exists(output_video):
        return
    command = f"ffmpeg.exe -i {video_file} -i {audio_file} -i {overlay_file} -filter_complex 'overlay=1540:780' \
    -t {duration}s \
    -preset ultrafast \
    -v quiet -stats \
    {output_video}"
    print(f"executing... {command}")
    subprocess.run(command, shell=True)


def get_meeting_duration(metadata_file):
    if not os.path.exists(metadata_file):
        return
    doc = ET.parse(metadata_file)
    return float(doc.find('playback').find('duration').text) / 1000


def get_video_duration(video_file):
    if not os.path.exists(video_file):
        return
    command = f"ffprobe -i {video_file} -show_format -v quiet -stats | grep duration | sed -n 's/duration=//p'"
    print(f"executing... {command}")
    result = subprocess.run(command, shell=True, capture_output=True)
    return float(result.stdout)


def get_video_framerate(video_file):
    command = f"ffprobe -v 0 -of compact=p=0 -select_streams 0 -show_entries stream=r_frame_rate -i {video_file}"
    print(f"executing... {command}")
    result = subprocess.run(command, shell=True, capture_output=True)
    m = re.search(b'^(r_frame_rate=)(.*)$', result.stdout)
    return int(eval(m.group(2)))


def convert_secs_to_hms(duration):
    return '0' + str(datetime.timedelta(seconds=duration))


def extract_number(x):
    m = re.search('^(image)([0-9]+)(.mp4)$', x)
    return int(m.group(2))


def check_utils():
    try:
        devnull = open(os.devnull)
        subprocess.Popen([f"ffmpeg", "-version"], stdout=devnull, stderr=devnull).communicate()
        subprocess.Popen([f"ffprobe", "-version"], stdout=devnull, stderr=devnull).communicate()
    except OSError as e:
        if e.errno == errno.ENOENT:
            return False
    return True


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 script.py <bbb url>')
        sys.exit(1)

    if not check_utils():
        print('Utilities: ffmpeg/ffprobe missing')
        sys.exit(1)

    url = sys.argv[1]
    meeting_id = download(url)
    duration = get_meeting_duration(os.path.join(meeting_id, 'metadata.xml'))
    durationL = convert_secs_to_hms(duration)
    framerate = get_video_framerate(os.path.join(meeting_id, 'video/webcams.mp4'))

    print('Duration:', duration, 'seconds =>', durationL)
    print('Frame rate:', framerate)

    print('Processing, slides to images...')
    create_slides(meeting_id,
                  os.path.join(meeting_id, 'output-video', 'slides'),
                  duration,
                  framerate)

    print('Merging, slides into video...')
    concat_video(os.path.join(meeting_id, 'output-video', 'slides'),
                 os.path.join(meeting_id, 'output-video', 'video-slides.mp4'))

    print('Extracting, audio from webcams...')
    extract_audio(os.path.join(meeting_id, 'video/webcams.mp4'),
                  os.path.join(meeting_id, 'output-video', 'audio-slides.m4a'),
                  round(duration))

    print('Extracting, overlay from webcams...')
    generate_overlay(os.path.join(meeting_id, 'video/webcams.mp4'),
                     os.path.join(meeting_id, 'output-video', 'overlay-webcams.mp4'),
                     round(duration))

    print('Merging, slides, audio and overlay...')
    merge_video_audio_overlay(os.path.join(meeting_id, 'output-video', 'video-slides.mp4'),
                              os.path.join(meeting_id, 'output-video', 'audio-slides.m4a'),
                              os.path.join(meeting_id, 'output-video', 'overlay-webcams.mp4'),
                              os.path.join(meeting_id, 'output-video', 'final.mp4'),
                              round(duration))

    print('End of the program.')
