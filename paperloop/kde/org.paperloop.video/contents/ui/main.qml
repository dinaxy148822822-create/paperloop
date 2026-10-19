import QtQuick
import QtMultimedia
import org.kde.plasma.plasmoid

// Paperloop Video: a Plasma wallpaper that loops a video (muted). The paperloop daemon writes
// VideoUrl and Paused into this wallpaper's configuration; both are applied live.
WallpaperItem {
    id: root

    readonly property url videoUrl: root.configuration.VideoUrl
    readonly property bool paused: root.configuration.Paused

    Rectangle { anchors.fill: parent; color: "black" }

    MediaPlayer {
        id: player
        source: root.videoUrl
        loops: MediaPlayer.Infinite
        videoOutput: output
        audioOutput: AudioOutput { muted: true }
        Component.onCompleted: if (!root.paused && root.videoUrl.toString() !== "") play()
    }

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    onPausedChanged: paused ? player.pause() : player.play()
    onVideoUrlChanged: if (!paused && videoUrl.toString() !== "") player.play()
}
