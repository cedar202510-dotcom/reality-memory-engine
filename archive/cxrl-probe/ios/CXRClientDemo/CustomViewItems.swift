//
//  CustomViewItems.swift
//  CXRClientDemo
//
//  Created by yubing on 2026/3/31.
//

import Foundation

// 定义图标数据结构体
struct IconData: Codable {
    // base64编码的图片数据
    let data: String
    // 图标名称
    let name: String
}

// 定义自定义视图数据结构体
struct CustomViewData: Codable {
    let type: String
    let props: [String: String]
    let children: [CustomViewData]?
    
    // 自定义编码器，确保props字段正确编码为字典而不是字符串
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(type, forKey: .type)
        try container.encode(props, forKey: .props)
        try container.encodeIfPresent(children, forKey: .children)
    }
    
    // 直接生成符合要求的JSON字符串
    func toJsonString() -> String {
        do {
            let jsonData = try JSONEncoder().encode(self)
            guard let jsonString = String(data: jsonData, encoding: .utf8) else {
                print("CustomViewData JSON数据转换为字符串失败")
                return ""
            }
            return jsonString
        } catch {
            print("CustomViewData JSON编码失败: \(error)")
            return ""
        }
    }
}

struct UpdateCustomViewData: Codable {
    let action: String
    let id: String
    let props: [String: String]
    
    // 自定义编码器，确保props字段正确编码为字典而不是字符串
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(action, forKey: .action)
        try container.encode(id, forKey: .id)
        try container.encode(props, forKey: .props)
    }
    
    // 直接生成符合要求的JSON字符串
    func toJsonString() -> String {
        do {
            let jsonData = try JSONEncoder().encode(self)
            guard let jsonString = String(data: jsonData, encoding: .utf8) else {
                print("UpdateCustomViewData JSON数据转换为字符串失败")
                return ""
            }
            return jsonString
        } catch {
            print("UpdateCustomViewData JSON编码失败: \(error)")
            return ""
        }
    }
}

struct ViewLayout: Codable {
    // 视图ID
    var id: String? = nil
    // 视图宽度（如：match_parent, wrap_content, 具体数值）
    let layout_width: String
    // 视图高度（如：match_parent, wrap_content, 具体数值）
    let layout_height: String
    // 布局方向（如：vertical, horizontal）
    let orientation: String
    // 内容对齐方式（如：center, left, right, top, bottom）
    var gravity: String
    // 起始边距
    var marginStart: String? = nil
    // 结束边距
    var marginEnd: String? = nil
    // 顶部边距
    var marginTop: String? = nil
    // 底部边距
    var marginBottom: String? = nil
    // 起始内边距
    var paddingStart: String? = nil
    // 结束内边距
    var paddingEnd: String? = nil
    // 顶部内边距
    var paddingTop: String? = nil
    // 底部内边距
    var paddingBottom: String? = nil
    // 背景颜色（十六进制格式）
    var backgroundColor: String
    
    func toPropsDictionary() -> [String: String] {
        var props: [String: String] = [:]
        
        props["id"] = id
        props["layout_width"] = layout_width
        props["layout_height"] = layout_height
        props["orientation"] = orientation
        props["gravity"] = gravity
        if let paddingStart = paddingStart { props["paddingStart"] = paddingStart }
        if let paddingEnd = paddingEnd { props["paddingEnd"] = paddingEnd }
        if let paddingTop = paddingTop { props["paddingTop"] = paddingTop }
        if let paddingBottom = paddingBottom { props["paddingBottom"] = paddingBottom }
        if let marginStart = marginStart { props["marginStart"] = marginStart }
        if let marginEnd = marginEnd { props["marginEnd"] = marginEnd }
        if let marginTop = marginTop { props["marginTop"] = marginTop }
        if let marginBottom = marginBottom { props["marginBottom"] = marginBottom }
        
        return props
    }
}

struct TextView: Codable {
    // 图片视图ID
    var id: String
    // 宽度（如：match_parent, wrap_content, 具体数值）
    let layout_width: String
    // 高度（如：match_parent, wrap_content, 具体数值）
    let layout_height: String
    // 包裹内容
    var wrap_content: String? = nil
    // 文本内容
    let text: String
    // 文本颜色
    let textColor: String
    // 文本大小
    let textSize: String
    // 内容对齐方式（如：center, left, right, top, bottom）
    var gravity: String? = nil
    // 文本类型
    var textStyle: String? = nil
    // 起始内边距
    var paddingStart: String? = nil
    // 结束内边距
    var paddingEnd: String? = nil
    // 顶部内边距
    var paddingTop: String? = nil
    // 底部内边距
    var paddingBottom: String? = nil
    // 起始边距
    var marginStart: String? = nil
    // 结束边距
    var marginEnd: String? = nil
    // 顶部边距
    var marginTop: String? = nil
    // 底部边距
    var marginBottom: String? = nil
    // 位于某个视图的起始位置
    var layout_toStartOf: String? = nil
    // 位于某个视图的上方
    var layout_above: String? = nil
    // 位于某个视图的结束位置
    var layout_toEndOf: String? = nil
    // 位于某个视图的下方
    var layout_below: String? = nil
    // 与某个视图的基线对齐
    var layout_alignBaseLine: String? = nil
    // 与某个视图的起始位置对齐
    var layout_alignStart: String? = nil
    // 与某个视图的结束位置对齐
    var layout_alignEnd: String? = nil
    // 与某个视图的顶部对齐
    var layout_alignTop: String? = nil
    // 与某个视图的底部对齐
    var layout_alignBottom: String? = nil
    // 与父视图的起始位置对齐
    var layout_alignParentStart: String? = nil
    // 与父视图的结束位置对齐
    var layout_alignParentEnd: String? = nil
    // 与父视图的顶部对齐
    var layout_alignParentTop: String? = nil
    // 与父视图的底部对齐
    var layout_alignParentBottom: String? = nil
    // 在父视图中居中
    var layout_centerInParent: String? = nil
    // 水平居中
    var layout_centerHorizontal: String? = nil
    // 垂直居中
    var layout_centerVertical: String? = nil
    
    // 将TextView实例转换为字典
    func toPropsDictionary() -> [String: String] {
        var props: [String: String] = [:]
        props["id"] = id
        props["layout_width"] = layout_width
        props["layout_height"] = layout_height
        if let wrap_content = wrap_content { props["wrap_content"] = wrap_content }
        props["text"] = text
        props["textColor"] = textColor
        props["textSize"] = textSize
        if let gravity = gravity { props["gravity"] = gravity }
        if let textStyle = textStyle { props["textStyle"] = textStyle }
        if let paddingStart = paddingStart { props["paddingStart"] = paddingStart }
        if let paddingEnd = paddingEnd { props["paddingEnd"] = paddingEnd }
        if let paddingTop = paddingTop { props["paddingTop"] = paddingTop }
        if let paddingBottom = paddingBottom { props["paddingBottom"] = paddingBottom }
        if let marginStart = marginStart { props["marginStart"] = marginStart }
        if let marginEnd = marginEnd { props["marginEnd"] = marginEnd }
        if let marginTop = marginTop { props["marginTop"] = marginTop }
        if let marginBottom = marginBottom { props["marginBottom"] = marginBottom }
        if let layout_toStartOf = layout_toStartOf { props["layout_toStartOf"] = layout_toStartOf }
        if let layout_above = layout_above { props["layout_above"] = layout_above }
        if let layout_toEndOf = layout_toEndOf { props["layout_toEndOf"] = layout_toEndOf }
        if let layout_below = layout_below { props["layout_below"] = layout_below }
        if let layout_alignBaseLine = layout_alignBaseLine { props["layout_alignBaseLine"] = layout_alignBaseLine }
        if let layout_alignStart = layout_alignStart { props["layout_alignStart"] = layout_alignStart }
        if let layout_alignEnd = layout_alignEnd { props["layout_alignEnd"] = layout_alignEnd }
        if let layout_alignTop = layout_alignTop { props["layout_alignTop"] = layout_alignTop }
        if let layout_alignBottom = layout_alignBottom { props["layout_alignBottom"] = layout_alignBottom }
        if let layout_alignParentStart = layout_alignParentStart { props["layout_alignParentStart"] = layout_alignParentStart }
        if let layout_alignParentEnd = layout_alignParentEnd { props["layout_toStartOf"] = layout_alignParentEnd }
        if let layout_alignParentTop = layout_alignParentTop { props["layout_toStartOf"] = layout_alignParentTop }
        if let layout_alignParentBottom = layout_alignParentBottom { props["layout_alignParentBottom"] = layout_alignParentBottom }
        if let layout_centerInParent = layout_centerInParent { props["layout_centerInParent"] = layout_centerInParent }
        if let layout_centerHorizontal = layout_centerHorizontal { props["layout_centerHorizontal"] = layout_centerHorizontal }
        if let layout_centerVertical = layout_centerVertical { props["layout_centerVertical"] = layout_centerVertical }
        return props
    }
}

struct ImageView: Codable {
    // 图片视图ID
    let id: String?
    // 宽度（如：match_parent, wrap_content, 具体数值）
    let layout_width: String?
    // 高度（如：match_parent, wrap_content, 具体数值）
    let layout_height: String?
    // 图片名称（对应发送的图标名称）
    let name: String?
    // 图片缩放类型（如：centerCrop, fitCenter, fitXY）
    var scaleType: String? = nil
    // 位于某个视图的起始位置
    var layout_toStartOf: String? = nil
    // 位于某个视图的上方
    var layout_above: String? = nil
    // 位于某个视图的结束位置
    var layout_toEndOf: String? = nil
    // 位于某个视图的下方
    var layout_below: String? = nil
    // 与某个视图的基线对齐
    var layout_alignBaseLine: String? = nil
    // 与某个视图的起始位置对齐
    var layout_alignStart: String? = nil
    // 与某个视图的结束位置对齐
    var layout_alignEnd: String? = nil
    // 与某个视图的顶部对齐
    var layout_alignTop: String? = nil
    // 与某个视图的底部对齐
    var layout_alignBottom: String? = nil
    // 与父视图的起始位置对齐
    var layout_alignParentStart: String? = nil
    // 与父视图的结束位置对齐
    var layout_alignParentEnd: String? = nil
    // 与父视图的顶部对齐
    var layout_alignParentTop: String? = nil
    // 与父视图的底部对齐
    var layout_alignParentBottom: String? = nil
    // 在父视图中居中
    var layout_centerInParent: String? = nil
    // 水平居中
    var layout_centerHorizontal: String? = nil
    // 垂直居中
    var layout_centerVertical: String? = nil
    
    func toPropsDictionary() -> [String: String] {
        var props: [String: String] = [:]
        props["id"] = id
        props["layout_width"] = layout_width
        props["layout_height"] = layout_height
        props["name"] = name
        if let scaleType = scaleType { props["scaleType"] = scaleType }
        if let layout_toStartOf = layout_toStartOf { props["layout_toStartOf"] = layout_toStartOf }
        if let layout_above = layout_above { props["layout_above"] = layout_above }
        if let layout_toEndOf = layout_toEndOf { props["layout_toEndOf"] = layout_toEndOf }
        if let layout_below = layout_below { props["layout_below"] = layout_below }
        if let layout_alignBaseLine = layout_alignBaseLine { props["layout_alignBaseLine"] = layout_alignBaseLine }
        if let layout_alignStart = layout_alignStart { props["layout_alignStart"] = layout_alignStart }
        if let layout_alignEnd = layout_alignEnd { props["layout_alignEnd"] = layout_alignEnd }
        if let layout_alignTop = layout_alignTop { props["layout_alignTop"] = layout_alignTop }
        if let layout_alignBottom = layout_alignBottom { props["layout_alignBottom"] = layout_alignBottom }
        if let layout_alignParentStart = layout_alignParentStart { props["layout_alignParentStart"] = layout_alignParentStart }
        if let layout_alignParentEnd = layout_alignParentEnd { props["layout_toStartOf"] = layout_alignParentEnd }
        if let layout_alignParentTop = layout_alignParentTop { props["layout_toStartOf"] = layout_alignParentTop }
        if let layout_alignParentBottom = layout_alignParentBottom { props["layout_alignParentBottom"] = layout_alignParentBottom }
        if let layout_centerInParent = layout_centerInParent { props["layout_centerInParent"] = layout_centerInParent }
        if let layout_centerHorizontal = layout_centerHorizontal { props["layout_centerHorizontal"] = layout_centerHorizontal }
        if let layout_centerVertical = layout_centerVertical { props["layout_centerVertical"] = layout_centerVertical }
        return props
    }
}
